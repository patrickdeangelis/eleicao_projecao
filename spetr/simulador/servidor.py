"""
Simulador local da CDN do TSE.

Gera, a partir do eleitorado real de cada município (spetr/data), arquivos no formato
"Dados Simplificados" com a apuração avançando no tempo:
- cada unidade (cidade estratificada ou interior remanescente) tem velocidade de apuração
  própria por região e tipo, comparecimento e preferências regionais;
- o arquivo da UF é a soma das unidades (consistente com a subtração da heurística);
- suporta HTTP 304 (If-Modified-Since) e um painel de controle em "/".

Pode rodar embutido no SPETR (SimuladorLocal) ou isolado (scripts/mock_tse_server.py).
"""
import asyncio
import email.utils
import hashlib
import html
import json
import socket
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

import uvicorn
from fastapi import FastAPI, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Caminho da eleição simulada (formato "r"): /oficial/ele2022/545/dados-simplificados/...
ANO_SIMULADO = "2022"
ELEICAO_SIMULADA = "545"

REGIAO = {
    "AC": "N", "AM": "N", "AP": "N", "PA": "N", "RO": "N", "RR": "N", "TO": "N",
    "AL": "NE", "BA": "NE", "CE": "NE", "MA": "NE", "PB": "NE", "PE": "NE", "PI": "NE", "RN": "NE", "SE": "NE",
    "DF": "CO", "GO": "CO", "MS": "CO", "MT": "CO",
    "ES": "SE", "MG": "SE", "RJ": "SE", "SP": "SE",
    "PR": "S", "RS": "S", "SC": "S", "ZZ": "EX",
}
# Velocidade relativa de apuração (o Sudeste e o exterior demoram mais; capitais apuram antes do interior)
VELOCIDADE_REGIAO = {"N": 1.10, "NE": 1.25, "CO": 1.05, "SE": 0.85, "S": 1.00, "EX": 0.70}
VELOCIDADE_TIPO = {"cidade": 1.15, "interior": 0.90}

# Cenários fictícios: (numero, nome, partido, participação base nos válidos, destinação)
CENARIOS = {
    "1t": [
        ("99", "LUCAS SILVA", "PSOC", 0.405, "Válido"),
        ("88", "MARCOS SANTOS", "PPRO", 0.392, "Válido"),
        ("45", "ANA COSTA", "PNOV", 0.072, "Válido"),
        ("30", "PEDRO ALVES", "PLIB", 0.048, "Válido"),
        ("50", "JULIA ROCHA", "PVER", 0.031, "Válido"),
        ("15", "RAFAEL LIMA", "PDEM", 0.022, "Válido"),
        ("16", "BEATRIZ NUNES", "PTRAB", 0.015, "Válido"),
        ("27", "CARLOS MOURA", "PCRIS", 0.010, "Válido"),
        ("80", "HELENA DIAS", "PUNI", 0.005, "Válido"),
        ("77", "JOSE FERREIRA", "PIND", 0.012, "Anulado sub judice"),
    ],
    "2t": [
        ("99", "LUCAS SILVA", "PSOC", 0.506, "Válido"),
        ("88", "MARCOS SANTOS", "PPRO", 0.494, "Válido"),
    ],
}
DESCRICAO_CENARIOS = {
    "1t": "1º turno · 10 candidatos fictícios (um sub judice)",
    "2t": "2º turno · 2 candidatos fictícios",
}
# Ritmo do relógio da simulação: (segundos entre avanços, avanço em fração das seções)
VELOCIDADES = {
    "lenta": (10.0, 0.01),
    "normal": (6.0, 0.02),
    "rapida": (4.0, 0.05),
}
# Inclinação regional e cidade x interior para os dois primeiros candidatos
INCLINACAO_REGIAO = {"N": -0.02, "NE": 0.14, "CO": -0.09, "SE": -0.04, "S": -0.08, "EX": -0.03}
INCLINACAO_CIDADE = -0.03


def _agora_http() -> str:
    # Data HTTP (RFC 7231) independente do locale: com a janela GTK o processo fica em pt_BR,
    # e time.strftime("%a %b") geraria "sáb, 03 out", que não é um cabeçalho HTTP válido.
    return email.utils.formatdate(usegmt=True)


def formatar_tse_int(val: int) -> str:
    """Formata com pontos de milhar padrão TSE (ex: 1.250.400)."""
    return f"{val:,}".replace(",", ".")


def formatar_tse_float(val: float) -> str:
    """Formata percentual com vírgula padrão TSE (ex: 51,82)."""
    return f"{val:.2f}".replace(".", ",")


def _ruido(chave: str, amplitude: float) -> float:
    """Ruído determinístico em [-amplitude, amplitude] por unidade (estável entre requisições)."""
    h = int(hashlib.sha256(chave.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return (h * 2.0 - 1.0) * amplitude


class EstadoSimulacao:
    """Estado mutável de uma simulação de apuração."""

    def __init__(
        self,
        cenario: str = "1t",
        velocidade: str = "normal",
        progresso_inicial: float = 0.0,
        data_dir: Path = DATA_DIR,
    ):
        if cenario not in CENARIOS:
            raise ValueError(f"Cenário desconhecido: {cenario!r}. Opções: {list(CENARIOS)}")
        if velocidade not in VELOCIDADES:
            raise ValueError(f"Velocidade desconhecida: {velocidade!r}. Opções: {list(VELOCIDADES)}")
        self.cenario = cenario
        self.velocidade = velocidade
        self.velocidade_segundos, self.passo_progresso = VELOCIDADES[velocidade]
        self.progresso_global: float = min(1.0, max(0.0, progresso_inicial))
        self.pausado: bool = False
        self.versao_ciclo: int = 1
        self.ultima_modificacao: str = _agora_http()
        self.candidatos = [
            {"n": n, "nm": nm, "cc": cc, "meta_pct": meta, "dvt": dvt}
            for n, nm, cc, meta, dvt in CENARIOS[cenario]
        ]
        self.ufs_data: Dict[str, Any] = {}
        self.cidades_data: Dict[str, List[str]] = {}
        self.municipios_meta: Dict[str, Any] = {}
        for nome, attr in (("ufs_metadados.json", "ufs_data"), ("cidades_100k.json", "cidades_data"),
                           ("municipios_meta.json", "municipios_meta")):
            path = data_dir / nome
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    setattr(self, attr, json.load(f))

    def _marcar_mudanca(self) -> None:
        self.versao_ciclo += 1
        self.ultima_modificacao = _agora_http()

    def avancar(self, delta: Optional[float] = None) -> None:
        d = delta if delta is not None else self.passo_progresso
        self.progresso_global = min(1.0, max(0.0, self.progresso_global + d))
        self._marcar_mudanca()

    def definir(self, fracao: float) -> None:
        self.progresso_global = min(1.0, max(0.0, fracao))
        self._marcar_mudanca()

    def resetar(self) -> None:
        self.definir(0.0)

    # ------------------------------------------------------------ modelo

    def unidades_da_uf(self, uf: str) -> List[Dict[str, Any]]:
        """Cidades estratificadas (eleitorado real) + interior remanescente da UF."""
        uf_meta = self.ufs_data.get(uf, {"secoes": 5000, "eleitores": 1500000})
        unidades = []
        sec_cid = eleit_cid = 0
        for cod in self.cidades_data.get(uf, []):
            m = self.municipios_meta.get(f"{uf}_{cod}", {})
            sec, el = int(m.get("secoes", 300)), int(m.get("eleitores", 100000))
            unidades.append({"id": f"{uf}_{cod}", "tipo": "cidade", "secoes": sec, "eleitores": el})
            sec_cid += sec
            eleit_cid += el
        unidades.append({
            "id": f"{uf}_INTERIOR", "tipo": "interior",
            "secoes": max(1, uf_meta.get("secoes", 5000) - sec_cid),
            "eleitores": max(1000, uf_meta.get("eleitores", 1500000) - eleit_cid),
        })
        return unidades

    def apurar_unidade(self, uf: str, u: Dict[str, Any]) -> Dict[str, Any]:
        """Números apurados de uma unidade no progresso global atual."""
        regiao = REGIAO.get(uf, "SE")
        velocidade = VELOCIDADE_REGIAO[regiao] * VELOCIDADE_TIPO[u["tipo"]] * (1.0 + _ruido(u["id"] + "v", 0.08))
        p = min(1.0, self.progresso_global * velocidade) if self.progresso_global < 1.0 else 1.0
        apuradas = int(round(u["secoes"] * p))
        eleit_apurados = int(u["eleitores"] * apuradas / u["secoes"])

        taxa_comp = 0.80 + _ruido(u["id"] + "c", 0.04)
        comparecimento = int(eleit_apurados * taxa_comp)
        brancos = int(comparecimento * 0.022)
        nulos = int(comparecimento * 0.035)
        nominais = comparecimento - brancos - nulos

        pesos = [c["meta_pct"] for c in self.candidatos]
        inclinacao = INCLINACAO_REGIAO[regiao] + (INCLINACAO_CIDADE if u["tipo"] == "cidade" else 0.0) + _ruido(u["id"], 0.05)
        if len(pesos) >= 2:
            pesos[0] = max(0.01, pesos[0] + inclinacao / 2)
            pesos[1] = max(0.01, pesos[1] - inclinacao / 2)
        for i in range(2, len(pesos)):
            pesos[i] *= 1.0 + _ruido(u["id"] + str(i), 0.5)
        soma = sum(pesos)
        votos = [int(nominais * w / soma) for w in pesos]
        votos[0] += nominais - sum(votos)

        return {
            "secoes": u["secoes"], "apuradas": apuradas, "eleitores": u["eleitores"],
            "comparecimento": comparecimento, "abstencao": eleit_apurados - comparecimento,
            "brancos": brancos, "nulos": nulos, "votos": votos,
        }

    def somar(self, partes: List[Dict[str, Any]]) -> Dict[str, Any]:
        total: Dict[str, Any] = {k: 0 for k in ("secoes", "apuradas", "eleitores", "comparecimento", "abstencao", "brancos", "nulos")}
        total["votos"] = [0] * len(self.candidatos)
        for p in partes:
            for k in total:
                if k == "votos":
                    total["votos"] = [a + b for a, b in zip(total["votos"], p["votos"])]
                else:
                    total[k] += p[k]
        return total

    def gerar_payload(self, totais: Dict[str, Any]) -> Dict[str, Any]:
        """Dicionário no formato do JSON dados-simplificados do TSE."""
        validos = sum(v for v, c in zip(totais["votos"], self.candidatos) if c["dvt"] == "Válido")
        anulados = sum(totais["votos"]) - validos
        p_final = self.progresso_global >= 1.0
        ordem = sorted(range(len(self.candidatos)), key=lambda i: -totais["votos"][i])
        cand = []
        for i, c in enumerate(self.candidatos):
            v = totais["votos"][i]
            valido = c["dvt"] == "Válido"
            cand.append({
                "n": c["n"], "nm": c["nm"], "cc": c["cc"], "dvt": c["dvt"],
                "vap": formatar_tse_int(v),
                "pvap": formatar_tse_float(v / max(1, validos) * 100.0 if valido else 0.0),
                "st": ("Eleito" if i == ordem[0] else "Não eleito") if p_final else "",
            })
        return {
            "dg": time.strftime("%d/%m/%Y"),
            "hg": time.strftime("%H:%M:%S"),
            "f": "o",
            "st": formatar_tse_int(totais["apuradas"]),
            "s": formatar_tse_int(totais["secoes"]),
            "pst": formatar_tse_float(totais["apuradas"] / max(1, totais["secoes"]) * 100.0),
            "e": formatar_tse_int(totais["eleitores"]),
            "c": formatar_tse_int(totais["comparecimento"]),
            "a": formatar_tse_int(totais["abstencao"]),
            "vv": formatar_tse_int(validos),
            "vvc": formatar_tse_int(validos + anulados),
            "van": formatar_tse_int(anulados),
            "vb": formatar_tse_int(totais["brancos"]),
            "vn": formatar_tse_int(totais["nulos"]),
            "cand": cand,
        }

    def resumo(self) -> Dict[str, Any]:
        return {
            "progresso": round(self.progresso_global * 100.0, 2),
            "pausado": self.pausado,
            "ciclo": self.versao_ciclo,
            "ultima_modificacao": self.ultima_modificacao,
            "cenario": self.cenario,
            "velocidade": self.velocidade,
            "candidatos": self.candidatos,
        }


def _painel_html(estado: EstadoSimulacao) -> str:
    e = html.escape
    p_pct = estado.progresso_global * 100.0
    ritmo = f"+{estado.passo_progresso * 100:.0f}% a cada {estado.velocidade_segundos:.0f}s"
    candidatos = "".join(
        f"<li><strong>Nº {e(c['n'])} · {e(c['nm'])}</strong> ({e(c['cc'])}) · base {c['meta_pct'] * 100:.1f}% · {e(c['dvt'])}</li>"
        for c in estado.candidatos
    )
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Simulador de apuração</title>
  <style>
    :root {{ color-scheme: light dark; --fundo: #f9f9f7; --cartao: #fcfcfb; --texto: #0b0b0b; --texto2: #52514e; --borda: rgba(11,11,11,.1); --acao: #2a78d6; }}
    @media (prefers-color-scheme: dark) {{ :root {{ --fundo: #0d0d0d; --cartao: #1a1a19; --texto: #fff; --texto2: #c3c2b7; --borda: rgba(255,255,255,.1); --acao: #3987e5; }} }}
    body {{ font-family: system-ui, -apple-system, "Segoe UI", sans-serif; background: var(--fundo); color: var(--texto); margin: 0; padding: 24px 16px; }}
    .cartao {{ background: var(--cartao); border: 1px solid var(--borda); border-radius: 12px; max-width: 760px; margin: 0 auto; padding: 24px; }}
    h1 {{ margin: 0 0 4px; font-size: 1.2rem; }}
    .sub {{ color: var(--texto2); margin: 0 0 20px; }}
    .pct {{ font-size: 3rem; font-weight: 700; }}
    .barra {{ height: 8px; background: var(--borda); border-radius: 4px; overflow: hidden; margin: 8px 0 20px; }}
    .barra span {{ display: block; height: 100%; background: var(--acao); }}
    .botoes {{ display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 20px; }}
    button {{ font: inherit; border: 1px solid var(--borda); background: var(--fundo); color: var(--texto); padding: 8px 14px; border-radius: 8px; cursor: pointer; }}
    button.primario {{ background: var(--acao); color: #fff; border-color: var(--acao); }}
    ul {{ color: var(--texto2); padding-left: 18px; }}
  </style>
</head>
<body>
  <div class="cartao">
    <h1>Simulador de apuração</h1>
    <p class="sub">{e(DESCRICAO_CENARIOS[estado.cenario])} · ritmo {e(ritmo)} · {'pausado' if estado.pausado else 'em andamento'}</p>
    <div class="pct" id="pct">{p_pct:.1f}%</div>
    <div class="barra"><span style="width:{p_pct:.1f}%"></span></div>
    <div class="botoes">
      <button class="primario" data-acao="toggle">{'▶ Retomar' if estado.pausado else '⏸ Pausar'}</button>
      <button data-acao="step?delta=0.05">+5%</button>
      <button data-acao="set?pct=25">Ir para 25%</button>
      <button data-acao="set?pct=50">Ir para 50%</button>
      <button data-acao="set?pct=95">Ir para 95%</button>
      <button data-acao="reset">Voltar a 0%</button>
    </div>
    <p><strong>Candidatos</strong></p>
    <ul>{candidatos}</ul>
  </div>
  <script>
    document.querySelectorAll('[data-acao]').forEach((b) => b.addEventListener('click', () =>
      fetch('/mock/control/' + b.dataset.acao, {{ method: 'POST' }}).then(() => location.reload())));
    setInterval(() => fetch('/mock/control/status').then((r) => r.json()).then((s) => {{
      document.getElementById('pct').textContent = s.progresso.toFixed(1) + '%';
    }}), 2000);
  </script>
</body>
</html>"""


def criar_app_simulador(estado: EstadoSimulacao) -> FastAPI:
    """Cria a aplicação FastAPI que espelha a CDN do TSE para o estado informado."""

    async def ticker() -> None:
        while True:
            await asyncio.sleep(estado.velocidade_segundos)
            if not estado.pausado and estado.progresso_global < 1.0:
                estado.avancar()

    @asynccontextmanager
    async def ciclo_de_vida(_app: FastAPI):
        tarefa = asyncio.create_task(ticker())
        try:
            yield
        finally:
            tarefa.cancel()

    app = FastAPI(title="Simulador da CDN do TSE", lifespan=ciclo_de_vida, docs_url=None, redoc_url=None)

    @app.get("/oficial/ele{ano}/{eleicao}/dados-simplificados/{uf}/{arquivo}")
    async def arquivo_simplificado(ano: str, eleicao: str, uf: str, arquivo: str, request: Request):
        """
        Ex: /oficial/ele2022/545/dados-simplificados/pb/pb-c0001-e000545-r.json  (UF = soma das unidades)
        Ex: /oficial/ele2022/545/dados-simplificados/pb/pb20516-c0001-e000545-r.json
        """
        if request.headers.get("if-modified-since") == estado.ultima_modificacao:
            return Response(status_code=304)

        uf_sigla = uf.upper()
        nome_limpo = arquivo.lower().replace(uf.lower(), "", 1)
        unidades = estado.unidades_da_uf(uf_sigla)
        if nome_limpo.startswith("-"):
            totais = estado.somar([estado.apurar_unidade(uf_sigla, u) for u in unidades])
        else:
            cod_mun = nome_limpo.split("-")[0]
            alvo = next((u for u in unidades if u["id"] == f"{uf_sigla}_{cod_mun}"), None)
            if alvo is None:
                return Response(status_code=404)
            totais = estado.apurar_unidade(uf_sigla, alvo)

        headers = {
            "Last-Modified": estado.ultima_modificacao,
            "ETag": f'W/"sim-{estado.versao_ciclo}"',
        }
        return JSONResponse(content=estado.gerar_payload(totais), headers=headers)

    @app.get("/", response_class=HTMLResponse)
    async def painel():
        return _painel_html(estado)

    @app.post("/mock/control/step")
    async def passo(delta: float = Query(default=0.05, ge=-1.0, le=1.0)):
        estado.avancar(delta)
        return estado.resumo()

    @app.post("/mock/control/set")
    async def definir(pct: float = Query(..., ge=0.0, le=100.0)):
        estado.definir(pct / 100.0)
        return estado.resumo()

    @app.post("/mock/control/reset")
    async def resetar():
        estado.resetar()
        return estado.resumo()

    @app.post("/mock/control/toggle")
    async def alternar():
        estado.pausado = not estado.pausado
        return estado.resumo()

    @app.get("/mock/control/status")
    async def status():
        return estado.resumo()

    return app


def porta_livre(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


class SimuladorLocal:
    """Executa o simulador em uma porta local livre, no mesmo loop de eventos do SPETR."""

    def __init__(self, estado: EstadoSimulacao, host: str = "127.0.0.1", porta: Optional[int] = None):
        self.estado = estado
        self.host = host
        self.porta = porta or porta_livre(host)
        self._servidor: Optional[uvicorn.Server] = None
        self._tarefa: Optional[asyncio.Task] = None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.porta}"

    async def iniciar(self, timeout: float = 10.0) -> str:
        config = uvicorn.Config(
            criar_app_simulador(self.estado), host=self.host, port=self.porta,
            log_level="warning", access_log=False, lifespan="on",
        )
        self._servidor = uvicorn.Server(config)
        self._tarefa = asyncio.create_task(self._servidor.serve())
        limite = time.monotonic() + timeout
        while not self._servidor.started:
            if self._tarefa.done():
                raise RuntimeError(f"Simulador não iniciou na porta {self.porta}")
            if time.monotonic() > limite:
                raise TimeoutError("Simulador demorou demais para iniciar")
            await asyncio.sleep(0.05)
        return self.url

    async def parar(self) -> None:
        if self._servidor is not None:
            self._servidor.should_exit = True
        if self._tarefa is not None:
            try:
                await asyncio.wait_for(self._tarefa, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._tarefa.cancel()
        self._servidor = None
        self._tarefa = None
