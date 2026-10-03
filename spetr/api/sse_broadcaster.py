"""
Distribuidor de Server-Sent Events (SSE) para a interface do SPETR.
"""
import asyncio
import json
from typing import Set, Dict, Any, Optional
import logging

from spetr.domain.interfaces import IEventBus
from spetr.services.events import ProjectionCalculatedEvent

logger = logging.getLogger("spetr.api.sse")


class SSEBroadcaster:
    """Gerencia conexões de clientes SSE ativos e distribui atualizações."""

    def __init__(self, event_bus: Optional[IEventBus] = None):
        self.bus = event_bus
        self._queues: Set[asyncio.Queue] = set()
        self.ultimo_resultado_json: Optional[str] = None

        if self.bus is not None:
            self.bus.subscribe(ProjectionCalculatedEvent, self.ao_calcular_projecao)

    async def ao_calcular_projecao(self, evento: ProjectionCalculatedEvent) -> None:
        p = evento.resultado
        payload = {
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
            "candidatos": [
                {
                    "numero": c.numero,
                    "nome": c.nome,
                    "partido": c.partido,
                    "cor_hex": c.cor_hex,
                    "votos_apurados": c.votos_apurados,
                    "perc_apurado": c.perc_apurado,
                    "media_projetada": c.media_projetada,
                    "perc_projetado": c.perc_projetado,
                    "ic_inferior_95": c.ic_inferior_95,
                    "ic_superior_95": c.ic_superior_95,
                    "prob_vitoria": c.prob_vitoria,
                }
                for c in p.candidatos
            ]
        }
        self.ultimo_resultado_json = json.dumps(payload)
        await self.broadcast(self.ultimo_resultado_json)

    async def connect(self) -> asyncio.Queue:
        q = asyncio.Queue(maxsize=50)
        self._queues.add(q)
        # Se já tivermos uma projeção na memória, envia imediatamente ao novo cliente conectado
        if self.ultimo_resultado_json:
            await q.put(self.ultimo_resultado_json)
        return q

    def disconnect(self, q: asyncio.Queue) -> None:
        self._queues.discard(q)

    async def broadcast(self, mensagem_json: str) -> None:
        for q in list(self._queues):
            try:
                if q.full():
                    try:
                        q.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                q.put_nowait(mensagem_json)
            except Exception as e:
                logger.warning(f"Erro ao entregar mensagem a cliente SSE: {e}")
