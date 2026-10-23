"""
Distribuidor de Server-Sent Events (SSE) para a interface do SPETR.
"""
import asyncio
import json
from typing import Set, Dict, Any, Optional
import logging

from spetr.domain.interfaces import IEventBus
from spetr.domain.entities import ResultadoProjecao
from spetr.domain.value_objects import CHAVES_RESUMO_ANALISE
from spetr.services.events import CollectionErrorEvent, CollectionFinishedEvent, ProjectionCalculatedEvent

logger = logging.getLogger("spetr.api.sse")



def serializar_resultado(p: ResultadoProjecao, completo: bool = True) -> Dict[str, Any]:
    """Formato único usado por SSE, histórico (completo=False) e time-travel."""
    analise = p.analise or {}
    if not completo:
        analise = {k: analise.get(k) for k in CHAVES_RESUMO_ANALISE}
    return {
        "timestamp": p.timestamp,
        "ciclo_id": p.ciclo_id,
        "total_secoes": p.total_secoes,
        "secoes_apuradas": p.secoes_apuradas,
        "perc_secoes_apuradas": p.perc_secoes_apuradas,
        "total_eleitores": p.total_eleitores,
        "total_validos_apurados": p.total_validos_apurados,
        "total_validos_projetados": p.total_validos_projetados,
        "status_call": p.status_call.value if hasattr(p.status_call, "value") else str(p.status_call),
        "vencedor_projetado": p.vencedor_projetado,
        "lider_margem": p.lider_margem,
        "tempo_computacao_ms": p.tempo_computacao_ms,
        "prob_segundo_turno": p.prob_segundo_turno,
        "ufs_sem_dados": p.ufs_sem_dados,
        "candidatos": [
            {
                "numero": c.numero,
                "nome": c.nome,
                "partido": c.partido,
                "votos_apurados": c.votos_apurados,
                "perc_apurado": c.perc_apurado,
                "media_projetada": c.media_projetada,
                "perc_projetado": c.perc_projetado,
                "ic_inferior_95": c.ic_inferior_95,
                "ic_superior_95": c.ic_superior_95,
                "prob_vitoria": c.prob_vitoria,
                "prob_lideranca": c.prob_lideranca,
                "vice": c.vice,
                "coligacao": c.coligacao,
                "composicao": c.composicao,
                "nome_completo": c.nome_completo,
            }
            for c in p.candidatos
        ],
        "analise": analise,
    }


class SSEBroadcaster:
    """Gerencia conexões de clientes SSE ativos e distribui atualizações.

    Cada mensagem na fila é um par (evento, dados_json):
    - "projecao_update": novo resultado da projeção
    - "aviso": falha de coleta (ex.: arquivos do TSE ainda não publicados)
    - "sessao": a sessão foi iniciada, parada ou trocada de modo
    - "coleta_encerrada": a apuração chegou a 100% e a coleta parou
    """

    def __init__(self, event_bus: Optional[IEventBus] = None):
        self.bus = event_bus
        self._queues: Set[asyncio.Queue] = set()
        self.ultimo_resultado_json: Optional[str] = None
        self.ultimo_aviso: Optional[Dict[str, Any]] = None
        self.coleta_encerrada: Optional[Dict[str, Any]] = None

        if self.bus is not None:
            self.bus.subscribe(ProjectionCalculatedEvent, self.ao_calcular_projecao)
            self.bus.subscribe(CollectionErrorEvent, self.ao_erro_coleta)
            self.bus.subscribe(CollectionFinishedEvent, self.ao_coleta_encerrada)

    async def ao_calcular_projecao(self, evento: ProjectionCalculatedEvent) -> None:
        self.ultimo_resultado_json = json.dumps(serializar_resultado(evento.resultado), separators=(",", ":"))
        await self.broadcast(self.ultimo_resultado_json)

    async def ao_erro_coleta(self, evento: CollectionErrorEvent) -> None:
        self.ultimo_aviso = {"timestamp": evento.timestamp, "origem": evento.origem, "mensagem": evento.mensagem}
        await self.broadcast(json.dumps(self.ultimo_aviso), evento_sse="aviso")

    async def ao_coleta_encerrada(self, evento: CollectionFinishedEvent) -> None:
        self.coleta_encerrada = {"timestamp": evento.timestamp, "ciclo_id": evento.ciclo_id, "mensagem": evento.mensagem}
        self.ultimo_aviso = None
        await self.broadcast(json.dumps(self.coleta_encerrada), evento_sse="coleta_encerrada")

    async def ao_mudar_sessao(self, sessao: Dict[str, Any]) -> None:
        """Nova sessão: descarta o último resultado (de outro modo/eleição) e avisa os painéis abertos."""
        self.ultimo_resultado_json = None
        self.ultimo_aviso = None
        self.coleta_encerrada = None
        await self.broadcast(json.dumps({"ativa": sessao.get("ativa"), "modo": sessao.get("modo")}), evento_sse="sessao")

    async def connect(self) -> asyncio.Queue:
        q = asyncio.Queue(maxsize=50)
        self._queues.add(q)
        # Se já tivermos uma projeção na memória, envia imediatamente ao novo cliente conectado
        if self.ultimo_resultado_json:
            await q.put(("projecao_update", self.ultimo_resultado_json))
        return q

    def disconnect(self, q: asyncio.Queue) -> None:
        self._queues.discard(q)

    async def broadcast(self, mensagem_json: str, evento_sse: str = "projecao_update") -> None:
        for q in list(self._queues):
            try:
                if q.full():
                    try:
                        q.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                q.put_nowait((evento_sse, mensagem_json))
            except Exception as e:
                logger.warning(f"Erro ao entregar mensagem a cliente SSE: {e}")
