"""
Script de Simulação e Replay Realista da Apuração de 2022.
Executa a evolução cronológica das urnas (Nordeste abrindo com velocidade,
Sudeste consolidando depois) e permite assistir à convergência da projeção.
"""
import sys
import os
import time
import asyncio
import threading
import uvicorn

# Garante import do spetr
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from spetr.services.event_bus import EventBus
from spetr.services.events import RawBatchReceivedEvent
from spetr.services.pipeline_coordinator import PipelineCoordinator
from spetr.api.server import create_api_app


def gerar_lote_simulado(pct_global: float) -> dict:
    """Gera payloads simulados para os estados e grandes cidades."""
    lote = {}

    # Curva regional: Nordeste abre antes (mais rápido no início), Sudeste abre mais tarde
    fator_ne = min(1.0, pct_global * 1.35)
    fator_se = max(0.0, (pct_global - 0.05) * 0.95) if pct_global > 0.05 else 0.02
    fator_sul = min(1.0, pct_global * 1.1)

    # 1. Caso Paraíba
    sec_tot_pb = 10338
    sec_apu_pb = int(sec_tot_pb * fator_ne)
    val_tot_pb = int(sec_apu_pb * 240)
    # No total da PB real de 2022: Lula ~66.6%, Bolsonaro ~33.4%
    votos_lula_pb = int(val_tot_pb * 0.666)
    votos_bolso_pb = val_tot_pb - votos_lula_pb

    lote["UF_PB"] = {
        "s": str(sec_tot_pb), "st": str(sec_apu_pb), "e": "3056480",
        "c": str(int(val_tot_pb * 1.2)), "a": str(int(val_tot_pb * 0.25)),
        "vvc": str(val_tot_pb), "vb": str(int(val_tot_pb * 0.03)), "vn": str(int(val_tot_pb * 0.04)),
        "cand": [
            {"n": "13", "nm": "Lula", "cc": "PT", "vap": str(votos_lula_pb), "pvap": "66,60"},
            {"n": "22", "nm": "Bolsonaro", "cc": "PL", "vap": str(votos_bolso_pb), "pvap": "33,40"}
        ]
    }

    # João Pessoa (20516) - Lula 54% x 46%
    sec_tot_jp = 2050
    sec_apu_jp = int(sec_tot_jp * fator_ne)
    val_jp = int(sec_apu_jp * 240)
    v_lula_jp = int(val_jp * 0.54)
    lote["MUN_PB_20516"] = {
        "s": str(sec_tot_jp), "st": str(sec_apu_jp), "e": "560000",
        "c": str(int(val_jp * 1.2)), "a": str(int(val_jp * 0.25)),
        "vvc": str(val_jp), "vb": "1000", "vn": "1000",
        "cand": [
            {"n": "13", "nm": "Lula", "cc": "PT", "vap": str(v_lula_jp), "pvap": "54,00"},
            {"n": "22", "nm": "Bolsonaro", "cc": "PL", "vap": str(val_jp - v_lula_jp), "pvap": "46,00"}
        ]
    }

    # Campina Grande (19852) - Lula 48.5% x 51.5%
    sec_tot_cg = 1020
    sec_apu_cg = int(sec_tot_cg * fator_ne)
    val_cg = int(sec_apu_cg * 240)
    v_lula_cg = int(val_cg * 0.485)
    lote["MUN_PB_19852"] = {
        "s": str(sec_tot_cg), "st": str(sec_apu_cg), "e": "290000",
        "c": str(int(val_cg * 1.2)), "a": str(int(val_cg * 0.25)),
        "vvc": str(val_cg), "vb": "500", "vn": "500",
        "cand": [
            {"n": "13", "nm": "Lula", "cc": "PT", "vap": str(v_lula_cg), "pvap": "48,50"},
            {"n": "22", "nm": "Bolsonaro", "cc": "PL", "vap": str(val_cg - v_lula_cg), "pvap": "51,50"}
        ]
    }

    # 2. Caso São Paulo (SP) - Bolsonaro ~55.2%, Lula ~44.8%
    sec_tot_sp = 101626
    sec_apu_sp = int(sec_tot_sp * fator_se)
    val_tot_sp = int(sec_apu_sp * 260)
    v_bolso_sp = int(val_tot_sp * 0.552)
    v_lula_sp = val_tot_sp - v_bolso_sp

    lote["UF_SP"] = {
        "s": str(sec_tot_sp), "st": str(sec_apu_sp), "e": "34667793",
        "c": str(int(val_tot_sp * 1.22)), "a": str(int(val_tot_sp * 0.25)),
        "vvc": str(val_tot_sp), "vb": "10000", "vn": "10000",
        "cand": [
            {"n": "13", "nm": "Lula", "cc": "PT", "vap": str(v_lula_sp), "pvap": "44,80"},
            {"n": "22", "nm": "Bolsonaro", "cc": "PL", "vap": str(v_bolso_sp), "pvap": "55,20"}
        ]
    }

    # Capital SP (71072) - Lula ~53.5%, Bolsonaro ~46.5%
    sec_tot_cap_sp = 26500
    sec_apu_cap_sp = int(sec_tot_cap_sp * fator_se)
    val_cap_sp = int(sec_apu_cap_sp * 260)
    v_lula_cap_sp = int(val_cap_sp * 0.535)
    lote["MUN_SP_71072"] = {
        "s": str(sec_tot_cap_sp), "st": str(sec_apu_cap_sp), "e": "9300000",
        "c": str(int(val_cap_sp * 1.22)), "a": str(int(val_cap_sp * 0.25)),
        "vvc": str(val_cap_sp), "vb": "5000", "vn": "5000",
        "cand": [
            {"n": "13", "nm": "Lula", "cc": "PT", "vap": str(v_lula_cap_sp), "pvap": "53,50"},
            {"n": "22", "nm": "Bolsonaro", "cc": "PL", "vap": str(val_cap_sp - v_lula_cap_sp), "pvap": "46,50"}
        ]
    }

    return lote


async def rodar_simulacao():
    print("=" * 70)
    print(" SPETR // SIMULAÇÃO E REPLAY DA APURAÇÃO 2022")
    print("=" * 70)

    bus = EventBus()
    coordinator = PipelineCoordinator(
        event_bus=bus,
        db_path="spetr_simulacao.sqlite",
        num_simulacoes=5000,
        ano_eleicao="2022",
        codigo_eleicao="545",
        turno=2,
        formato="r",
    )
    # A simulação só gera PB e SP: restringe o universo a essas UFs para que as demais
    # não entrem na projeção como "sem dados" (projetadas pelo prior).
    coordinator.engine.inicializar_ufs({}, prior_padrao=coordinator.engine.prior_padrao)
    api_app = create_api_app(event_bus=bus, repository=coordinator.repo)

    # Inicia servidor web local em background
    porta = 48291
    config = uvicorn.Config(api_app, host="127.0.0.1", port=porta, log_level="error")
    server = uvicorn.Server(config)
    asyncio.create_task(server.serve())

    print(f"\n[INFO] Dashboard disponível em: http://127.0.0.1:{porta}")
    print("[INFO] Pressione Enter para disparar a simulação passo-a-passo...\n")
    await asyncio.sleep(1.0)

    # Passos da apuração (5% até 100%)
    estagios = [0.05, 0.12, 0.22, 0.35, 0.50, 0.68, 0.82, 0.95, 1.00]

    for ciclo_id, pct in enumerate(estagios, start=1):
        print(f"\n--- [CICLO {ciclo_id}] Simulando Urnas Apuradas: {pct * 100:.1f}% ---")
        lote = gerar_lote_simulado(pct)

        ts = time.strftime("%H:%M:%S")
        await bus.publish(
            RawBatchReceivedEvent(
                timestamp=ts,
                ciclo_id=ciclo_id,
                total_arquivos=len(lote),
                arquivos_modificados=len(lote),
                payload_bruto=lote
            )
        )

        # Aguarda brevemente para que os inscritos processem e exibam
        await asyncio.sleep(2.5)

    print("\n[OK] Simulação de apuração concluída com sucesso!")
    print(f"Abra http://127.0.0.1:{porta} para visualizar o painel interativo e os gráficos de convergência.")
    await asyncio.sleep(3.0)


if __name__ == "__main__":
    asyncio.run(rodar_simulacao())
