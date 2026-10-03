"""
Teste de Integração do Pipeline Completo com EventBus e Persistência SQLite.
Valida o fluxo desacoplado:
RawBatchReceived -> StrataNormalized -> ProjectionCalculated -> SQLite & SSE.
"""
import pytest
import asyncio
import os
import tempfile
from spetr.services.event_bus import EventBus
from spetr.services.events import RawBatchReceivedEvent, ProjectionCalculatedEvent
from spetr.aggregator.vector_subtraction import VectorAggregator
from spetr.stats_engine.monte_carlo import MonteCarloProjectionEngine
from spetr.storage.database import SQLiteDatabase
from spetr.storage.repository import ElectionRepository
from spetr.api.sse_broadcaster import SSEBroadcaster
from spetr.domain.entities import EstratoEleitoral, Candidato
from spetr.domain.value_objects import TipoEstrato


@pytest.mark.asyncio
async def test_full_pipeline_flow():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_spetr.sqlite")

        bus = EventBus()
        db = SQLiteDatabase(db_path)
        repo = ElectionRepository(db, event_bus=bus)
        broadcaster = SSEBroadcaster(event_bus=bus)
        aggregator = VectorAggregator(
            event_bus=bus,
            cidades_100k_map={"PB": ["20516", "19852"]}
        )
        engine = MonteCarloProjectionEngine(event_bus=bus, num_simulacoes=2000)

        # Configura estratos
        estratos = [
            EstratoEleitoral(id="PB_20516", uf="PB", nome="João Pessoa", eleitores_aptos=560000, secoes_totais=2000, tipo=TipoEstrato.CAPITAL),
            EstratoEleitoral(id="PB_19852", uf="PB", nome="Campina Grande", eleitores_aptos=290000, secoes_totais=1000, tipo=TipoEstrato.GRANDE_CIDADE),
            EstratoEleitoral(id="PB_INTERIOR", uf="PB", nome="Interior", eleitores_aptos=2150000, secoes_totais=7000, tipo=TipoEstrato.INTERIOR_REMANESCENTE),
        ]
        engine.inicializar_estratos(estratos)
        engine.configurar_candidatos([
            Candidato(numero="13", nome="Lula", sigla_partido="PT"),
            Candidato(numero="22", nome="Bolsonaro", sigla_partido="PL")
        ])

        # Monitor de eventos disparados
        eventos_calculados = []
        async def capturar_projecao(evt: ProjectionCalculatedEvent):
            eventos_calculados.append(evt)
        bus.subscribe(ProjectionCalculatedEvent, capturar_projecao)

        # Lote simulado
        payload_bruto = {
            "UF_PB": {
                "s": "10000", "st": "2000", "e": "3000000", "c": "1600000", "a": "400000",
                "vvc": "1200000", "vb": "40000", "vn": "40000",
                "cand": [
                    {"n": "13", "vap": "780000", "pvap": "65,00"},
                    {"n": "22", "vap": "420000", "pvap": "35,00"}
                ]
            },
            "MUN_PB_20516": {
                "s": "2000", "st": "500", "e": "560000", "c": "250000", "a": "50000",
                "vvc": "200000", "vb": "10000", "vn": "10000",
                "cand": [
                    {"n": "13", "vap": "110000", "pvap": "55,00"},
                    {"n": "22", "vap": "90000", "pvap": "45,00"}
                ]
            },
            "MUN_PB_19852": {
                "s": "1000", "st": "250", "e": "290000", "c": "120000", "a": "30000",
                "vvc": "100000", "vb": "5000", "vn": "5000",
                "cand": [
                    {"n": "13", "vap": "49000", "pvap": "49,00"},
                    {"n": "22", "vap": "51000", "pvap": "51,00"}
                ]
            }
        }

        # 1. Injeta RawBatchReceivedEvent no EventBus
        await bus.publish(
            RawBatchReceivedEvent(
                timestamp="2022-10-30 17:35:00",
                ciclo_id=1,
                total_arquivos=3,
                arquivos_modificados=3,
                payload_bruto=payload_bruto
            )
        )

        # 2. Verifica se o evento de projeção foi calculado e propagado
        assert len(eventos_calculados) == 1
        resultado = eventos_calculados[0].resultado
        assert resultado.ciclo_id == 1
        assert resultado.secoes_apuradas > 0
        assert len(resultado.candidatos) == 2

        # 3. Verifica se o Broadcaster SSE capturou a projeção
        assert broadcaster.ultimo_resultado_json is not None
        assert "Lula" in broadcaster.ultimo_resultado_json

        # 4. Verifica se gravou no banco de dados SQLite
        historico = repo.obter_historico_projecoes(limite=10)
        assert len(historico) == 1
        assert historico[0].ciclo_id == 1
        assert historico[0].total_validos_apurados > 0
