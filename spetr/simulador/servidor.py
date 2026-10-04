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
# Multiplicador de tempo por tipo de unidade: capitais/cidades grandes apuram antes do interior
VELOCIDADE_TIPO = {"cidade": 1.15, "interior": 0.90}

# Perfis dos cenários fictícios.
# candidatos: (numero, nome, partido, participação base nos válidos, destinação)
# inclinacao_regiao: pontos somados ao 1º candidato (e tirados do 2º) em cada região, ÷ 2
# apuracao: curva de cada região sobre o relógio global t ∈ [0, 1]:
#   ("razao", r)   -> 1 − (1 − t)^r  (r = razão de velocidade: 2 começa no dobro do ritmo médio,
#                                     0,5 começa na metade e acelera no fim; sempre termina em 100%)
#   ("linear", v)  -> t × v          (cenários 1t/2t: v > 1 adianta; v < 1 atrasa)
#   ("inicio", k) / ("fim", k)       -> 1 − (1 − t)^k / t^k
_LINEAR_PADRAO = {"N": ("linear", 1.10), "NE": ("linear", 1.25), "CO": ("linear", 1.05),
                  "SE": ("linear", 0.85), "S": ("linear", 1.00), "EX": ("linear", 0.70)}
PERFIS: Dict[str, Dict[str, Any]] = {
    "1t": {
        "turno": 1,
        "descricao": "1º turno · 10 candidatos fictícios (um sub judice)",
        "candidatos": [
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
        "inclinacao_regiao": {"N": -0.02, "NE": 0.14, "CO": -0.09, "SE": -0.04, "S": -0.08, "EX": -0.03},
        "inclinacao_cidade": -0.03,
        "apuracao": _LINEAR_PADRAO,
    },
    "2t": {
        "turno": 2,
        "descricao": "2º turno · 2 candidatos fictícios",
        "candidatos": [
            ("99", "LUCAS SILVA", "PSOC", 0.506, "Válido"),
            ("88", "MARCOS SANTOS", "PPRO", 0.494, "Válido"),
        ],
        "inclinacao_regiao": {"N": -0.02, "NE": 0.14, "CO": -0.09, "SE": -0.04, "S": -0.08, "EX": -0.03},
        "inclinacao_cidade": -0.03,
        "apuracao": _LINEAR_PADRAO,
    },
    "virada": {
        "turno": 2,
        "descricao": "2º turno com virada · Nordeste (forte para SILVA) apura cedo; Sul, Sudeste e Centro-Oeste (fortes para SANTOS) apuram tarde",
        "candidatos": [
            ("99", "LUCAS SILVA", "PSOC", 0.482, "Válido"),
            ("88", "MARCOS SANTOS", "PPRO", 0.518, "Válido"),
        ],
        "inclinacao_regiao": {"N": 0.06, "NE": 0.34, "CO": -0.14, "SE": -0.12, "S": -0.16, "EX": -0.06},
        "inclinacao_cidade": -0.02,
        "apuracao": {"NE": ("razao", 3.0), "N": ("razao", 1.0), "CO": ("razao", 0.55),
                     "SE": ("razao", 0.4), "S": ("razao", 0.5), "EX": ("razao", 0.35)},
    },
}
# Viés de ordem: dentro de cada cidade/interior, as primeiras urnas favorecem SILVA e o efeito
# some até o fim (viola de propósito a suposição de que o já apurado representa o que falta).
PERFIS["vies"] = {
    **PERFIS["virada"],
    "descricao": "2º turno com viés de ordem · além da virada regional, as primeiras urnas de cada cidade favorecem SILVA",
    "vies_ordem": {"N": 0.10, "NE": 0.10, "CO": 0.14, "SE": 0.14, "S": 0.14, "EX": 0.10},
}

CENARIOS = {nome: p["candidatos"] for nome, p in PERFIS.items()}
DESCRICAO_CENARIOS = {nome: p["descricao"] for nome, p in PERFIS.items()}
TURNO_CENARIO = {nome: p["turno"] for nome, p in PERFIS.items()}

NOMES_REGIAO = {"N": "Norte", "NE": "Nordeste", "CO": "Centro-Oeste", "SE": "Sudeste", "S": "Sul", "EX": "Exterior"}
VELOCIDADE_TIPO_UNIFORME = {"cidade": 1.0, "interior": 1.0}
RAZAO_MIN, RAZAO_MAX = 0.2, 5.0


def _razao_equivalente(curva) -> float:
    """Razão de velocidade que melhor representa uma curva dos cenários prontos."""
    tipo, par = curva
    if tipo in ("razao", "inicio"):
        return round(par, 2)
    if tipo == "fim":
        return round(max(RAZAO_MIN, 1.0 / par), 2)
    return round(min(RAZAO_MAX, max(RAZAO_MIN, par)), 2)


_PERFIS_DESCRITOS: Optional[Dict[str, Any]] = None


def descrever_perfis() -> Dict[str, Any]:
    """
    Cada cenário pronto no formato dos ajustes (pré-preenche a configuração): percentual final de
    cada candidato em cada região e a razão de velocidade de cada região.
    """
    global _PERFIS_DESCRITOS
    if _PERFIS_DESCRITOS is None:
        saida = {}
        for nome, p in PERFIS.items():
            estado = EstadoSimulacao(nome)
            saida[nome] = {
                "descricao": p["descricao"],
                "turno": p["turno"],
                "candidatos": [{"n": c[0], "nm": c[1], "sub_judice": c[4] != "Válido"} for c in p["candidatos"]],
                "ajustes": {
                    "regioes": {
                        reg: {"percentuais": estado.percentuais_finais(reg),
                              "velocidade": _razao_equivalente(p["apuracao"].get(reg, ("linear", 1.0))),
                              "vies": round(p.get("vies_ordem", {}).get(reg, 0.0) * 100, 1)}
                        for reg in NOMES_REGIAO
                    },
                    "cidades_primeiro": True,
                },
            }
        _PERFIS_DESCRITOS = saida
    return _PERFIS_DESCRITOS


def _numero(valor: Any, nome: str, minimo: float, maximo: float) -> float:
    try:
        v = float(valor)
    except (TypeError, ValueError):
        raise ValueError(f"{nome}: valor inválido ({valor!r})")
    if not minimo <= v <= maximo:
        raise ValueError(f"{nome}: use um valor entre {minimo:g} e {maximo:g}")
    return v


def aplicar_ajustes(perfil: Dict[str, Any], ajustes: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Cópia do perfil com os ajustes do usuário:
    - regioes: {N|NE|CO|SE|S|EX: {percentuais: {numero: % dos votos nominais}, velocidade: razão (0,2 a 5),
               vies: viés de ordem em pontos (-40 a 40)}}
      Os percentuais de cada região precisam somar 100%. O viés de ordem é a vantagem extra do
      1º candidato sobre o 2º nas primeiras urnas de cada cidade/interior; diminui até zero no fim.
    - cidades_primeiro: capitais e cidades grandes apuram antes do interior
    """
    if not ajustes:
        return perfil
    numeros = [c[0] for c in perfil["candidatos"]]
    novo = {**perfil, "apuracao": dict(perfil["apuracao"]), "percentuais_regiao": {},
            "vies_ordem": dict(perfil.get("vies_ordem", {}))}
    for reg, cfg in (ajustes.get("regioes") or {}).items():
        if reg not in NOMES_REGIAO:
            raise ValueError(f"Região desconhecida: {reg!r}")
        nome_reg = NOMES_REGIAO[reg]
        if "percentuais" in cfg:
            pcts = {}
            for n, v in cfg["percentuais"].items():
                if n not in numeros:
                    raise ValueError(f"Candidato {n!r} não existe neste cenário")
                pcts[n] = _numero(v, f"{nome_reg}, candidato {n}", 0, 100)
            soma = sum(pcts.values())
            if abs(soma - 100) > 0.5:
                raise ValueError(f"Os percentuais de {nome_reg} somam {soma:.1f}%; precisam somar 100%")
            novo["percentuais_regiao"][reg] = {n: v / soma for n, v in pcts.items()}
        if "velocidade" in cfg:
            novo["apuracao"][reg] = ("razao", _numero(cfg["velocidade"], f"Velocidade de {nome_reg}", RAZAO_MIN, RAZAO_MAX))
        if "vies" in cfg:
            novo["vies_ordem"][reg] = _numero(cfg["vies"], f"Viés de ordem de {nome_reg}", -40, 40) / 100
    if "cidades_primeiro" in ajustes:
        novo["velocidade_tipo"] = VELOCIDADE_TIPO if ajustes["cidades_primeiro"] else VELOCIDADE_TIPO_UNIFORME
    return novo


# Ritmo do relógio da simulação: (segundos entre avanços, avanço em fração das seções)
VELOCIDADES = {
    "lenta": (10.0, 0.01),
    "normal": (6.0, 0.02),
    "rapida": (4.0, 0.05),
}


def progresso_por_curva(t: float, curva) -> float:
    """
    Fração apurada de uma unidade quando o relógio global está em t (0 a 1).
    ("razao", r): 1 − (1 − t)^r. r é a razão de velocidade: o ritmo no início em relação ao
    ritmo médio (r = 1 linear; r = 2 começa no dobro; r = 0,5 começa na metade e acelera no fim).
    Toda região chega a 100% em t = 1.
    """
    t = min(1.0, max(0.0, t))
    tipo, par = curva
    if tipo == "razao":
        return 1.0 - (1.0 - t) ** par
    if tipo == "inicio":
        return 1.0 - (1.0 - t) ** par
    if tipo == "fim":
        return t ** par
    return min(1.0, t * par)


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
        ajustes: Optional[Dict[str, Any]] = None,
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
        self.perfil = aplicar_ajustes(PERFIS[cenario], ajustes)
        self.personalizado = bool(ajustes)
        self.candidatos = [
            {"n": n, "nm": nm, "cc": cc, "meta_pct": meta, "dvt": dvt}
            for n, nm, cc, meta, dvt in self.perfil["candidatos"]
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
        # Relógio da unidade: o global, adiantado/atrasado pelo tipo (cidade × interior) e um ruído próprio
        t = self.progresso_global * self.perfil.get("velocidade_tipo", VELOCIDADE_TIPO)[u["tipo"]] * (1.0 + _ruido(u["id"] + "v", 0.08))
        curva = self.perfil["apuracao"].get(regiao, ("linear", 1.0))
        p = progresso_por_curva(t, curva) if self.progresso_global < 1.0 else 1.0
        apuradas = int(round(u["secoes"] * p))
        eleit_apurados = int(u["eleitores"] * apuradas / u["secoes"])

        taxa_comp = 0.80 + _ruido(u["id"] + "c", 0.04)
        comparecimento = int(eleit_apurados * taxa_comp)
        brancos = int(comparecimento * 0.022)
        nulos = int(comparecimento * 0.035)
        nominais = comparecimento - brancos - nulos

        definidos = self.perfil.get("percentuais_regiao", {}).get(regiao)
        if definidos:
            # Percentuais configurados para a região; cidades e interior variam um pouco em torno deles
            pesos = [definidos.get(c["n"], 0.0) for c in self.candidatos]
            inclinacao = (self.perfil["inclinacao_cidade"] if u["tipo"] == "cidade" else 0.0) + _ruido(u["id"], 0.03)
        else:
            pesos = [c["meta_pct"] for c in self.candidatos]
            inclinacao = (self.perfil["inclinacao_regiao"].get(regiao, 0.0)
                          + (self.perfil["inclinacao_cidade"] if u["tipo"] == "cidade" else 0.0)
                          + _ruido(u["id"], 0.05))
        # Viés de ordem: as urnas apuradas até aqui (p) pendem para o 1º candidato; com tudo
        # apurado (p = 1) o efeito é zero e o resultado final não muda
        inclinacao += self.perfil.get("vies_ordem", {}).get(regiao, 0.0) * (1.0 - p)
        if len(pesos) >= 2:
            pesos[0] = max(0.01, pesos[0] + inclinacao / 2)
            pesos[1] = max(0.01, pesos[1] - inclinacao / 2)
        for i in range(2, len(pesos)):
            pesos[i] *= 1.0 + _ruido(u["id"] + str(i), 0.2 if definidos else 0.5)
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

    def percentuais_finais(self, regiao: str) -> Dict[str, float]:
        """% de cada candidato nos votos nominais da região ao fim da apuração."""
        original = self.progresso_global
        self.progresso_global = 1.0
        try:
            t = self.somar([self.apurar_unidade(uf, u) for uf, r in REGIAO.items() if r == regiao
                            for u in self.unidades_da_uf(uf)])
        finally:
            self.progresso_global = original
        soma = sum(t["votos"]) or 1
        return {c["n"]: round(v / soma * 100, 1) for c, v in zip(self.candidatos, t["votos"])}

    def lote_completo(self) -> Dict[str, Dict[str, Any]]:
        """Todos os arquivos (UFs e cidades) no instante atual, com as chaves usadas pelo coletor."""
        lote: Dict[str, Dict[str, Any]] = {}
        for uf in REGIAO:
            partes = []
            for u in self.unidades_da_uf(uf):
                apurado = self.apurar_unidade(uf, u)
                partes.append(apurado)
                if u["tipo"] == "cidade":
                    lote[f"MUN_{u['id']}"] = self.gerar_payload(apurado)
            lote[f"UF_{uf}"] = self.gerar_payload(self.somar(partes))
        return lote

    def previa(self, marcos=(0.25, 0.5, 0.75)) -> Dict[str, Any]:
        """Resultado final esperado e quanto cada região terá apurado em alguns instantes."""
        original = self.progresso_global
        try:
            self.progresso_global = 1.0
            finais = {reg: self.somar([self.apurar_unidade(uf, u) for uf, r in REGIAO.items() if r == reg
                                       for u in self.unidades_da_uf(uf)]) for reg in sorted(set(REGIAO.values()))}
            total = self.somar(list(finais.values()))
            validos = [i for i, c in enumerate(self.candidatos) if c["dvt"] == "Válido"]

            def partes(t):
                soma = sum(t["votos"][i] for i in validos) or 1
                return {self.candidatos[i]["n"]: round(t["votos"][i] / soma * 100, 2) for i in validos}

            ritmo = {}
            for m in marcos:
                self.progresso_global = m
                por_reg = {}
                for reg in finais:
                    unidades = [self.apurar_unidade(uf, u) for uf, r in REGIAO.items() if r == reg for u in self.unidades_da_uf(uf)]
                    soma = self.somar(unidades)
                    por_reg[reg] = round(soma["apuradas"] / max(1, soma["secoes"]) * 100, 1)
                tudo = self.somar([self.apurar_unidade(uf, u) for uf in REGIAO for u in self.unidades_da_uf(uf)])
                ritmo[str(m)] = {"nacional": round(tudo["apuradas"] / max(1, tudo["secoes"]) * 100, 1),
                                 "regioes": por_reg, "parcial": partes(tudo)}
            return {"final": partes(total), "final_regioes": {r: partes(t) for r, t in finais.items()}, "ritmo": ritmo}
        finally:
            self.progresso_global = original

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
    <p class="sub">{e(DESCRICAO_CENARIOS[estado.cenario])}{' (personalizado)' if estado.personalizado else ''} · ritmo {e(ritmo)} · {'pausado' if estado.pausado else 'em andamento'}</p>
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
