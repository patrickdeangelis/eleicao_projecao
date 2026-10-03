"""
Rotas da API Local FastAPI do SPETR.
"""
import asyncio
import json
from typing import Optional
from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse

from spetr.api.sse_broadcaster import SSEBroadcaster
from spetr.domain.interfaces import IRepository

router = APIRouter(prefix="/api/v1")


def setup_routes(broadcaster: SSEBroadcaster, repo: Optional[IRepository] = None) -> APIRouter:

    @router.get("/status")
    async def get_status():
        return {
            "sistema": "SPETR - Sistema de Projeção Eleitoral em Tempo Real",
            "versao": "1.0.0",
            "status": "operacional"
        }

    @router.get("/projecao/atual")
    async def get_projecao_atual():
        if broadcaster.ultimo_resultado_json:
            return JSONResponse(content=json.loads(broadcaster.ultimo_resultado_json))
        return JSONResponse(content={"mensagem": "Aguardando primeiro ciclo de apuração"}, status_code=200)

    @router.get("/projecao/stream")
    async def sse_stream():
        """Canal Server-Sent Events em tempo real."""
        async def event_generator():
            q = await broadcaster.connect()
            try:
                # Envia handshake inicial
                yield ": sse handshake estabelecido\n\n"
                while True:
                    try:
                        # Timeout de 15 segundos para enviar heartbeat (keep-alive)
                        msg = await asyncio.wait_for(q.get(), timeout=15.0)
                        yield f"event: projecao_update\ndata: {msg}\n\n"
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
            finally:
                broadcaster.disconnect(q)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )

    @router.get("/projecao/historico")
    async def get_historico(limite: int = Query(default=100, le=500)):
        if repo is None:
            return []
        hist = repo.obter_historico_projecoes(limite=limite)
        return [
            {
                "timestamp": p.timestamp,
                "ciclo_id": p.ciclo_id,
                "secoes_apuradas": p.secoes_apuradas,
                "perc_secoes": p.perc_secoes_apuradas,
                "status_call": p.status_call.value if hasattr(p.status_call, "value") else str(p.status_call),
                "vencedor_projetado": p.vencedor_projetado,
                "lider_margem": p.lider_margem,
                "candidatos": [
                    {
                        "numero": c.numero,
                        "nome": c.nome,
                        "perc_apurado": c.perc_apurado,
                        "perc_projetado": c.perc_projetado,
                        "ic_inferior_95": c.ic_inferior_95,
                        "ic_superior_95": c.ic_superior_95,
                        "prob_vitoria": c.prob_vitoria
                    }
                    for c in p.candidatos
                ]
            }
            for p in hist
        ]

    @router.get("/projecao/time-travel")
    async def get_time_travel(timestamp: str = Query(...)):
        if repo is None:
            raise HTTPException(status_code=503, detail="Repositório não disponível")
        p = repo.obter_projecao_em_tempo(timestamp)
        if not p:
            raise HTTPException(status_code=404, detail="Nenhum snapshot encontrado para o timestamp informado")
        return {
            "timestamp": p.timestamp,
            "ciclo_id": p.ciclo_id,
            "secoes_apuradas": p.secoes_apuradas,
            "perc_secoes": p.perc_secoes_apuradas,
            "candidatos": [
                {
                    "numero": c.numero,
                    "nome": c.nome,
                    "perc_apurado": c.perc_apurado,
                    "perc_projetado": c.perc_projetado,
                    "ic_inferior_95": c.ic_inferior_95,
                    "ic_superior_95": c.ic_superior_95,
                    "prob_vitoria": c.prob_vitoria
                }
                for c in p.candidatos
            ]
        }

    return router
