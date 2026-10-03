"""
Servidor Mock da CDN do TSE (Tribunal Superior Eleitoral).
Simula com fidelidade matemática absoluta os endpoints oficiais da CDN do TSE,
gerando dados dinâmicos, progressão das urnas, suporte a HTTP 304 e painel de controle.
"""
import sys
import os
import json
import time
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional

import uvicorn
from fastapi import FastAPI, Request, Response, Query
from fastapi.responses import HTMLResponse, JSONResponse

# Diretório de dados estáticos do SPETR
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "spetr" / "data"

app = FastAPI(title="TSE Mock CDN Server")

# Estado Global da Simulação
class MockElectionState:
    def __init__(self):
        self.progresso_global: float = 0.00   # 0.0 a 1.0
        self.pausado: bool = False
        self.velocidade_segundos: float = 8.0 # avança a cada N segundos
        self.passo_progresso: float = 0.04    # avança 4% a cada ciclo
        self.versao_ciclo: int = 1
        self.ultima_modificacao: str = time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime())

        # Candidatos fictícios configuráveis
        self.candidato_1 = {
            "n": "99",
            "nm": "LUCAS SILVA",
            "cc": "PARTIDO SOCIAL",
            "meta_pct": 0.518 # 51.8% no final
        }
        self.candidato_2 = {
            "n": "88",
            "nm": "MARCOS SANTOS",
            "cc": "PARTIDO PROGRESSO",
            "meta_pct": 0.482 # 48.2% no final
        }

        # Carrega dados reais de UFs e Cidades
        self.ufs_data = {}
        self.cidades_data = {}
        self._carregar_dados()

    def _carregar_dados(self):
        ufs_path = DATA_DIR / "ufs_metadados.json"
        cidades_path = DATA_DIR / "cidades_100k.json"
        if ufs_path.exists():
            with open(ufs_path, "r", encoding="utf-8") as f:
                self.ufs_data = json.load(f)
        if cidades_path.exists():
            with open(cidades_path, "r", encoding="utf-8") as f:
                self.cidades_data = json.load(f)

    def avancar(self, delta: Optional[float] = None):
        d = delta if delta is not None else self.passo_progresso
        self.progresso_global = min(1.0, max(0.0, self.progresso_global + d))
        self.versao_ciclo += 1
        self.ultima_modificacao = time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime())

    def resetar(self):
        self.progresso_global = 0.0
        self.versao_ciclo += 1
        self.ultima_modificacao = time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime())

state = MockElectionState()


def formatar_tse_int(val: int) -> str:
    """Formata com pontos de milhar padrão TSE (ex: 1.250.400)."""
    return f"{val:,}".replace(",", ".")


def formatar_tse_float(val: float) -> str:
    """Formata percentual com vírgula padrão TSE (ex: 51,82)."""
    return f"{val:.2f}".replace(".", ",")


def gerar_payload_tse(secoes_total: int, eleitores_aptos: int, proporcao_cand1: float) -> Dict[str, Any]:
    """Gera um dicionário idêntico ao JSON dados-simplificados do TSE."""
    p = state.progresso_global
    secoes_apuradas = int(round(secoes_total * p))

    # Se zero apurado
    if secoes_apuradas == 0:
        return {
            "dg": time.strftime("%d/%m/%Y"),
            "hg": time.strftime("%H:%M:%S"),
            "f": "o", "st": "0", "s": formatar_tse_int(secoes_total), "pst": "0,00",
            "e": formatar_tse_int(eleitores_aptos), "c": "0", "pc": "0,00",
            "a": "0", "pa": "0,00", "vvc": "0", "vb": "0", "vn": "0",
            "cand": [
                {"n": state.candidato_1["n"], "nm": state.candidato_1["nm"], "cc": state.candidato_1["cc"], "vap": "0", "pvap": "0,00", "st": ""},
                {"n": state.candidato_2["n"], "nm": state.candidato_2["nm"], "cc": state.candidato_2["cc"], "vap": "0", "pvap": "0,00", "st": ""}
            ]
        }

    # Comparecimento e votos
    eleitores_por_secao = eleitores_aptos / max(1, secoes_total)
    eleitores_apurados = int(secoes_apuradas * eleitores_por_secao)

    taxa_comparecimento = 0.795
    comparecimento = int(eleitores_apurados * taxa_comparecimento)
    abstencao = eleitores_apurados - comparecimento

    votos_validos = int(comparecimento * 0.94)
    votos_brancos = int(comparecimento * 0.025)
    votos_nulos = comparecimento - votos_validos - votos_brancos

    # Distribuição entre os dois candidatos
    v1 = int(round(votos_validos * proporcao_cand1))
    v2 = votos_validos - v1

    pst = (secoes_apuradas / secoes_total) * 100.0
    pvap1 = (v1 / max(1, votos_validos)) * 100.0
    pvap2 = (v2 / max(1, votos_validos)) * 100.0

    return {
        "dg": time.strftime("%d/%m/%Y"),
        "hg": time.strftime("%H:%M:%S"),
        "f": "o",
        "st": formatar_tse_int(secoes_apuradas),
        "s": formatar_tse_int(secoes_total),
        "pst": formatar_tse_float(pst),
        "e": formatar_tse_int(eleitores_aptos),
        "c": formatar_tse_int(comparecimento),
        "pc": formatar_tse_float(taxa_comparecimento * 100.0),
        "a": formatar_tse_int(abstencao),
        "pa": formatar_tse_float((1.0 - taxa_comparecimento) * 100.0),
        "vvc": formatar_tse_int(votos_validos),
        "vb": formatar_tse_int(votos_brancos),
        "vn": formatar_tse_int(votos_nulos),
        "cand": [
            {
                "n": state.candidato_1["n"],
                "nm": state.candidato_1["nm"],
                "cc": state.candidato_1["cc"],
                "vap": formatar_tse_int(v1),
                "pvap": formatar_tse_float(pvap1),
                "st": "Eleito" if p >= 0.99 and v1 > v2 else ""
            },
            {
                "n": state.candidato_2["n"],
                "nm": state.candidato_2["nm"],
                "cc": state.candidato_2["cc"],
                "vap": formatar_tse_int(v2),
                "pvap": formatar_tse_float(pvap2),
                "st": "Não eleito" if p >= 0.99 and v1 > v2 else ""
            }
        ]
    }


# ==============================================================================
# ENDPOINTS OFICIAIS ESPELHADOS DO TSE
# ==============================================================================

@app.get("/oficial/ele{ano}/{eleicao}/dados-simplificados/{uf}/{arquivo}")
async def get_tse_simplificado(ano: str, eleicao: str, uf: str, arquivo: str, request: Request):
    """
    Simula exatamente o endpoint de dados simplificados da CDN do TSE:
    Ex: /oficial/ele2022/545/dados-simplificados/pb/pb-c0001-e000545-r.json
    Ex: /oficial/ele2022/545/dados-simplificados/pb/pb20516-c0001-e000545-r.json
    """
    # 1. Verifica cache condicional (If-Modified-Since)
    if_mod = request.headers.get("if-modified-since")
    if if_mod and if_mod == state.ultima_modificacao:
        return Response(status_code=304)

    uf_sigla = uf.upper()
    uf_meta = state.ufs_data.get(uf_sigla, {"secoes": 5000, "eleitores": 1500000})

    # Verifica se é município ou UF inteira
    # Padrão de município: pb20516-c0001...
    nome_limpo = arquivo.lower().replace(f"{uf.lower()}", "", 1)
    is_municipio = False
    cod_mun = None

    if nome_limpo.startswith("-"):
        # Arquivo de UF (ex: pb-c0001-e000545-r.json)
        secoes = uf_meta.get("secoes", 5000)
        eleitores = uf_meta.get("eleitores", 1500000)
    else:
        # Arquivo de Município (ex: pb20516-c0001-e000545-r.json)
        is_municipio = True
        cod_mun = nome_limpo.split("-")[0]
        # Estima dados do município
        secoes = int(uf_meta.get("secoes", 5000) * 0.20)
        eleitores = int(uf_meta.get("eleitores", 1500000) * 0.20)

    # Variação regional fictícia realista
    # Ex: no Nordeste Cand 1 tem mais votos; no Sul Cand 2 tem mais votos
    regioes_cand1 = {
        "PB": 0.65, "BA": 0.70, "PE": 0.67, "CE": 0.69, "MA": 0.71, "PI": 0.74, "RN": 0.64, "AL": 0.58, "SE": 0.63,
        "SP": 0.46, "RJ": 0.47, "MG": 0.51, "ES": 0.43,
        "PR": 0.36, "SC": 0.31, "RS": 0.44,
        "GO": 0.38, "MT": 0.35, "MS": 0.40, "DF": 0.42
    }
    base_cand1 = regioes_cand1.get(uf_sigla, state.candidato_1["meta_pct"])

    # Se for capital ou grande cidade, ajusta levemente
    if is_municipio:
        prop_final = base_cand1 - 0.06 # grandes cidades tendem a ser mais competitivas
    else:
        prop_final = base_cand1

    payload = gerar_payload_tse(secoes, eleitores, proporcao_cand1=prop_final)

    headers = {
        "Last-Modified": state.ultima_modificacao,
        "ETag": f'W/"mock-cycle-{state.versao_ciclo}"',
        "Content-Type": "application/json; charset=utf-8",
        "Server": "TSE-Mock-AkamaiGHost/1.0"
    }

    return JSONResponse(content=payload, headers=headers)


# ==============================================================================
# PAINEL WEB DE CONTROLE E DEPURAÇÃO (DASHBOARD DO MOCK)
# ==============================================================================

@app.get("/", response_class=HTMLResponse)
async def mock_dashboard():
    p_pct = state.progresso_global * 100.0
    return f"""
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
      <meta charset="UTF-8">
      <title>Painel de Controle - TSE Mock CDN</title>
      <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0B0F19; color: #E2E8F0; padding: 2rem; }}
        .card {{ background: #1A2234; border: 1px solid #2D3748; border-radius: 12px; max-width: 800px; margin: 0 auto; padding: 2rem; box-shadow: 0 10px 25px rgba(0,0,0,0.5); }}
        h1 {{ margin-top: 0; color: #38BDF8; font-size: 1.5rem; }}
        .status-badge {{ display: inline-block; padding: 0.35rem 0.75rem; border-radius: 6px; font-weight: bold; font-size: 0.85rem; margin-bottom: 1.5rem; }}
        .active {{ background: #065F46; color: #34D399; }}
        .paused {{ background: #854D0E; color: #FDE047; }}
        .progress-box {{ background: #0F172A; border-radius: 8px; padding: 1.5rem; margin-bottom: 1.5rem; text-align: center; }}
        .progress-pct {{ font-size: 3.5rem; font-weight: 900; color: #38BDF8; }}
        .btn-group {{ display: flex; gap: 0.75rem; flex-wrap: wrap; margin-bottom: 1.5rem; justify-content: center; }}
        button {{ background: #2563EB; color: #FFF; border: none; padding: 0.75rem 1.25rem; border-radius: 6px; font-weight: bold; cursor: pointer; transition: background 0.2s; }}
        button:hover {{ background: #1D4ED8; }}
        button.danger {{ background: #DC2626; }}
        button.danger:hover {{ background: #B91C1C; }}
        button.action {{ background: #059669; }}
        button.action:hover {{ background: #047857; }}
        .info-box {{ font-size: 0.85rem; color: #94A3B8; line-height: 1.6; border-top: 1px solid #2D3748; padding-top: 1.25rem; }}
        code {{ background: #0F172A; padding: 0.2rem 0.4rem; border-radius: 4px; color: #F1F5F9; font-family: monospace; }}
      </style>
    </head>
    <body>
      <div class="card">
        <h1>🌐 TSE Mock CDN Server // Modo Debug</h1>
        <div class="status-badge {'paused' if state.pausado else 'active'}">
          {'⏸ TICKER AUTOMÁTICO PAUSADO' if state.pausado else '▶ TICKER AUTOMÁTICO ATIVO (+4% a cada 8s)'}
        </div>

        <div class="progress-box">
          <div style="font-size: 0.85rem; color: #94A3B8; text-transform: uppercase;">Totalização Simulada das Urnas</div>
          <div class="progress-pct">{p_pct:.1f}%</div>
          <div style="font-size: 0.85rem; color: #94A3B8;">Ciclo Atual: #{state.versao_ciclo} &bull; Última Atualização: {state.ultima_modificacao}</div>
        </div>

        <div class="btn-group">
          <button onclick="fetch('/mock/control/toggle', {{method: 'POST'}}).then(() => location.reload())">
            {'▶ Retomar Ticker' if state.pausado else '⏸ Pausar Ticker'}
          </button>
          <button class="action" onclick="fetch('/mock/control/step?delta=0.05', {{method: 'POST'}}).then(() => location.reload())">
            ⏭ Avançar +5%
          </button>
          <button onclick="fetch('/mock/control/set?pct=50', {{method: 'POST'}}).then(() => location.reload())">
            🎯 Pular para 50%
          </button>
          <button onclick="fetch('/mock/control/set?pct=95', {{method: 'POST'}}).then(() => location.reload())">
            🏁 Pular para 95%
          </button>
          <button class="danger" onclick="fetch('/mock/control/reset', {{method: 'POST'}}).then(() => location.reload())">
            🔄 Resetar para 0%
          </button>
        </div>

        <div class="info-box">
          <p><strong>Candidatos Fictícios em Disputa:</strong></p>
          <ul>
            <li><strong>Nº {state.candidato_1['n']} - {state.candidato_1['nm']}</strong> ({state.candidato_1['cc']}) &bull; Meta Final: {state.candidato_1['meta_pct']*100:.1f}%</li>
            <li><strong>Nº {state.candidato_2['n']} - {state.candidato_2['nm']}</strong> ({state.candidato_2['cc']}) &bull; Meta Final: {state.candidato_2['meta_pct']*100:.1f}%</li>
          </ul>
          <p>Para conectar o SPETR neste servidor mock, execute em outro terminal:</p>
          <p><code>python main.py --mock</code></p>
        </div>
      </div>
    </body>
    </html>
    """

# ==============================================================================
# ROTAS REST DE CONTROLE DA SIMULAÇÃO
# ==============================================================================

@app.post("/mock/control/step")
async def control_step(delta: float = Query(default=0.05)):
    state.avancar(delta)
    return {"status": "ok", "progresso": state.progresso_global, "ciclo": state.versao_ciclo}

@app.post("/mock/control/set")
async def control_set(pct: float = Query(..., ge=0.0, le=100.0)):
    state.progresso_global = pct / 100.0
    state.versao_ciclo += 1
    state.ultima_modificacao = time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime())
    return {"status": "ok", "progresso": state.progresso_global, "ciclo": state.versao_ciclo}

@app.post("/mock/control/reset")
async def control_reset():
    state.resetar()
    return {"status": "ok", "progresso": 0.0, "ciclo": state.versao_ciclo}

@app.post("/mock/control/toggle")
async def control_toggle():
    state.pausado = not state.pausado
    return {"status": "ok", "pausado": state.pausado}

@app.get("/mock/control/status")
async def control_status():
    return {
        "progresso": round(state.progresso_global * 100.0, 2),
        "pausado": state.pausado,
        "ciclo": state.versao_ciclo,
        "ultima_modificacao": state.ultima_modificacao,
        "candidatos": [state.candidato_1, state.candidato_2]
    }


# ==============================================================================
# TICKER DE EVOLUÇÃO TEMPORAL EM BACKGROUND
# ==============================================================================

async def ticker_loop():
    """Avança a apuração realisticamente a cada ciclo de segundos."""
    while True:
        await asyncio.sleep(state.velocidade_segundos)
        if not state.pausado and state.progresso_global < 1.0:
            state.avancar()
            print(f"[TSE MOCK TICKER] Progresso da apuração avançou para: {state.progresso_global * 100:.1f}%")


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(ticker_loop())


if __name__ == "__main__":
    porta = 8080
    print("=" * 70)
    print(" TSE MOCK CDN SERVER // EMULADOR DE APURAÇÃO ELEITORAL")
    print(f" Endpoints TSE espelhados em: http://127.0.0.1:{porta}")
    print(f" Painel Web de Controle:     http://127.0.0.1:{porta}/")
    print("=" * 70)
    uvicorn.run(app, host="127.0.0.1", port=porta, log_level="warning")
