"""
Servidor local que espelha a CDN do TSE para o replay de uma apuração real.

Serve, no formato "Dados Simplificados" do TSE, os arquivos de UF e de município com os votos que
o estado de apuração (EstadoReplay, montado dos boletins de urna) já recebeu naquele instante:
- o arquivo da UF é a soma dos municípios (consistente com a subtração do agregador);
- suporta HTTP 304 (If-Modified-Since) e um painel de controle em "/".

Roda embutido no SPETR (SimuladorLocal), na mesma interface de coleta usada com o TSE.
"""
import asyncio
import email.utils
import html
import socket
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

import uvicorn
from fastapi import FastAPI, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse


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


class EstadoApuracao:
    """Base dos estados de apuração servidos: formata os totais no JSON do TSE."""

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


def _painel_html(estado: "EstadoApuracao") -> str:
    e = html.escape
    resumo = estado.resumo()
    p_pct = resumo["progresso"]
    ritmo = f"+{estado.minutos_por_passo} min da noite real a cada {estado.velocidade_segundos:.0f}s · {resumo['horario']}"
    descricao = estado.descricao
    def item(c):
        return f"<li><strong>Nº {e(c['n'])} · {e(c['nm'])}</strong> ({e(c['cc'])})</li>"
    candidatos = "".join(item(c) for c in estado.candidatos)
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Replay da apuração</title>
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
    <h1>Replay da apuração</h1>
    <p class="sub">{e(descricao)} · ritmo {e(ritmo)} · {'pausado' if estado.pausado else 'em andamento'}</p>
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
      fetch('/controle/' + b.dataset.acao, {{ method: 'POST' }}).then(() => location.reload())));
    setInterval(() => fetch('/controle/status').then((r) => r.json()).then((s) => {{
      document.getElementById('pct').textContent = s.progresso.toFixed(1) + '%';
    }}), 2000);
  </script>
</body>
</html>"""


def criar_app_simulador(estado: EstadoApuracao) -> FastAPI:
    """Cria a aplicação FastAPI que espelha a CDN do TSE para o estado de replay informado."""

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

    app = FastAPI(title="Replay da CDN do TSE", lifespan=ciclo_de_vida, docs_url=None, redoc_url=None)

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
            "ETag": f'W/"replay-{estado.versao_ciclo}"',
        }
        return JSONResponse(content=estado.gerar_payload(totais), headers=headers)

    @app.get("/", response_class=HTMLResponse)
    async def painel():
        return _painel_html(estado)

    @app.post("/controle/step")
    async def passo(delta: float = Query(default=0.05, ge=-1.0, le=1.0)):
        estado.avancar(delta)
        return estado.resumo()

    @app.post("/controle/set")
    async def definir(pct: float = Query(..., ge=0.0, le=100.0)):
        estado.definir(pct / 100.0)
        return estado.resumo()

    @app.post("/controle/reset")
    async def resetar():
        estado.resetar()
        return estado.resumo()

    @app.post("/controle/toggle")
    async def alternar():
        estado.pausado = not estado.pausado
        return estado.resumo()

    @app.get("/controle/status")
    async def status():
        return estado.resumo()

    return app


def porta_livre(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


class SimuladorLocal:
    """Executa o servidor de replay em uma porta local livre, no mesmo loop de eventos do SPETR."""

    def __init__(self, estado: EstadoApuracao, host: str = "127.0.0.1", porta: Optional[int] = None):
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
                raise RuntimeError(f"Servidor de replay não iniciou na porta {self.porta}")
            if time.monotonic() > limite:
                raise TimeoutError("Servidor de replay demorou demais para iniciar")
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
