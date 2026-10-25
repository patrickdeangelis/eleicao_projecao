"""
Rotas da API Local FastAPI do SPETR.
"""
import asyncio
import json
import time
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from spetr.api.sse_broadcaster import SSEBroadcaster, serializar_resultado
from spetr.domain.interfaces import IRepository


def verificar_origem(request: Request) -> None:
    """
    Bloqueia requisições que alteram estado vindas de outros sites abertos no navegador:
    exige JSON e, se houver cabeçalho Origin, que seja a própria origem do SPETR.
    """
    if not request.headers.get("content-type", "").startswith("application/json"):
        raise HTTPException(status_code=415, detail="Envie application/json")
    origem = request.headers.get("origin")
    if origem and origem != "null":
        alvo = urlparse(origem)
        if f"{alvo.hostname}:{alvo.port}" != f"{request.url.hostname}:{request.url.port}":
            raise HTTPException(status_code=403, detail="Origem não permitida")


def setup_routes(
    broadcaster: SSEBroadcaster,
    repo: Optional[IRepository] = None,
    info_eleicao: Optional[Dict[str, Any]] = None,
    sessao: Optional[Any] = None,
    publico: bool = False,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    def bloquear_se_publico() -> None:
        # Hospedagem pública: visitantes só leem; trocar/parar sessão e mudar a versão são do operador
        if publico:
            raise HTTPException(status_code=403, detail="Somente leitura nesta instância")

    def repositorio() -> Optional[IRepository]:
        return sessao.repo if sessao is not None else repo

    def info() -> Dict[str, Any]:
        return sessao.info if sessao is not None else (info_eleicao or {})

    @router.get("/healthz")
    async def healthz(max_idade: float = Query(default=120.0, ge=5.0, le=3600.0)):
        """Saúde da coleta: 200 se o último ciclo foi calculado há menos de `max_idade` segundos."""
        em = broadcaster.ultimo_resultado_em
        if em is None:
            return JSONResponse(status_code=503, content={"ok": False, "motivo": "sem ciclo calculado ainda"})
        idade = time.monotonic() - em
        corpo = {"ok": idade <= max_idade, "idade_ultimo_ciclo_s": round(idade, 1)}
        return JSONResponse(status_code=200 if corpo["ok"] else 503, content=corpo)

    @router.get("/status")
    async def get_status():
        return {
            "sistema": "SPETR - Sistema de Projeção Eleitoral em Tempo Real",
            "versao": "1.2.0",
            "status": "operacional",
            "eleicao": info(),
            "modo": sessao.modo if sessao is not None else None,
            "simulador_url": sessao.simulador.url if sessao is not None and sessao.simulador else None,
            "ultimo_aviso": broadcaster.ultimo_aviso,
            "coleta_encerrada": broadcaster.coleta_encerrada,
            "publico": publico,
        }

    # ---------------------------------------------------------------- sessão

    @router.get("/sessao")
    async def get_sessao():
        if sessao is None:
            return {"ativa": True, "modo": None, "eleicao": info()}
        return {**sessao.descrever(), "ultimo_aviso": broadcaster.ultimo_aviso, "coleta_encerrada": broadcaster.coleta_encerrada}

    @router.post("/sessao/iniciar")
    async def iniciar_sessao(request: Request, corpo: Dict[str, Any] = Body(...)):
        bloquear_se_publico()
        verificar_origem(request)
        if sessao is None:
            raise HTTPException(status_code=409, detail="Modo fixado na linha de comando")
        from spetr.services.sessao import ErroSessao
        try:
            return await sessao.iniciar(str(corpo.get("modo", "")), corpo.get("opcoes") or {})
        except ErroSessao as e:
            raise HTTPException(status_code=422, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Falha ao iniciar: {e}")

    @router.post("/sessao/parar")
    async def parar_sessao(request: Request):
        bloquear_se_publico()
        verificar_origem(request)
        if sessao is None:
            raise HTTPException(status_code=409, detail="Modo fixado na linha de comando")
        return await sessao.parar()

    @router.post("/projecao/versao")
    async def definir_versao(request: Request, corpo: Dict[str, Any] = Body(...)):
        """Versão que define os números principais e a chamada: subestratificado ou normal."""
        bloquear_se_publico()
        verificar_origem(request)
        from spetr.stats_engine.monte_carlo import VERSOES
        versao = str(corpo.get("versao", ""))
        if versao not in VERSOES:
            raise HTTPException(status_code=422, detail=f"Versão inválida: {versao!r}. Opções: {', '.join(VERSOES)}")
        coord = getattr(sessao, "coordinator", None) if sessao is not None else None
        if coord is None:
            raise HTTPException(status_code=409, detail="Nenhuma sessão ativa")
        coord.engine.versao_principal = versao
        return {"versao_principal": versao, "aplica_em": "próximo ciclo"}

    # -------------------------------------------------------------- projeção

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
                yield ": sse handshake estabelecido\n\n"
                while True:
                    try:
                        # Timeout de 15 segundos para enviar heartbeat (keep-alive)
                        evento, msg = await asyncio.wait_for(q.get(), timeout=15.0)
                        yield f"event: {evento}\ndata: {msg}\n\n"
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
    async def get_historico(limite: int = Query(default=2000, ge=1, le=5000)):
        """Série temporal da execução atual (resumo por ciclo) para as curvas do painel."""
        r = repositorio()
        if r is None:
            return []
        # O painel ignora ciclos sem votos; mandá-los custava ~80 MB retidos por visita (5.000 linhas com análise)
        hist = await asyncio.to_thread(r.obter_historico_projecoes, limite, True)
        return [serializar_resultado(p, completo=False) for p in hist]

    @router.get("/projecao/time-travel")
    async def get_time_travel(timestamp: str = Query(...)):
        r = repositorio()
        if r is None:
            raise HTTPException(status_code=503, detail="Nenhuma sessão ativa")
        p = await asyncio.to_thread(r.obter_projecao_em_tempo, timestamp)
        if not p:
            raise HTTPException(status_code=404, detail="Nenhum snapshot encontrado para o timestamp informado")
        return serializar_resultado(p)

    return router
