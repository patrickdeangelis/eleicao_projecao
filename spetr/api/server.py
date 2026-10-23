"""
Fábrica do servidor local FastAPI.
Serve a API REST/SSE e os arquivos estáticos do frontend.
"""
from pathlib import Path
from typing import Any, Dict, Optional
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse

from spetr.domain.interfaces import IEventBus, IRepository
from spetr.api.sse_broadcaster import SSEBroadcaster
from spetr.api.routes import setup_routes

UI_ASSETS_DIR = Path(__file__).parent.parent / "ui" / "assets"


def create_api_app(
    event_bus: Optional[IEventBus] = None,
    repository: Optional[IRepository] = None,
    broadcaster: Optional[SSEBroadcaster] = None,
    info_eleicao: Optional[Dict[str, Any]] = None,
    sessao: Optional[Any] = None,
    publico: bool = False,
) -> FastAPI:
    """
    sessao: SessaoSPETR que controla o modo (coleta real ou simulação). Sem ela, a API
    serve um pipeline fixo (repository/info_eleicao), como nos testes e scripts.
    """
    app = FastAPI(
        title="SPETR Local API",
        docs_url=None if publico else "/docs",
        openapi_url=None if publico else "/openapi.json",
        redoc_url=None
    )

    # Sem CORS: a UI (navegador ou PyWebView) é servida pela mesma origem da API,
    # e outros sites abertos no navegador não devem conseguir ler a API local.

    if broadcaster is None:
        broadcaster = SSEBroadcaster(event_bus)
    if sessao is not None:
        sessao.ao_mudar = broadcaster.ao_mudar_sessao

    # Registra rotas
    api_router = setup_routes(broadcaster, repository, info_eleicao=info_eleicao, sessao=sessao, publico=publico)
    app.include_router(api_router)

    # Raiz: painel se houver sessão ativa; senão, a tela inicial de escolha do modo
    @app.get("/")
    async def serve_index():
        if sessao is not None and not sessao.ativa:
            return RedirectResponse("/inicio", status_code=307)
        index_path = UI_ASSETS_DIR / "index.html"
        if index_path.exists():
            return FileResponse(index_path, headers={"Cache-Control": "no-store"})
        return {"status": "SPETR running. UI index not found."}

    @app.get("/inicio")
    async def serve_inicio():
        if publico:
            return RedirectResponse("/", status_code=307)
        return FileResponse(UI_ASSETS_DIR / "inicio.html", headers={"Cache-Control": "no-store"})

    # Arquivos do painel: o navegador/janela sempre revalida (ETag/304), para nunca exibir
    # uma versão antiga do painel guardada em cache depois de uma atualização do SPETR
    @app.middleware("http")
    async def sem_cache_do_painel(request, call_next):
        resposta = await call_next(request)
        if request.url.path.startswith("/static/"):
            resposta.headers["Cache-Control"] = "no-cache"
        return resposta

    # Monta arquivos estáticos
    if UI_ASSETS_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(UI_ASSETS_DIR)), name="static")

    return app
