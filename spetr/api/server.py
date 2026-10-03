"""
Fábrica do servidor local FastAPI.
Serve a API REST/SSE e os arquivos estáticos do frontend.
"""
from pathlib import Path
from typing import Optional
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from spetr.domain.interfaces import IEventBus, IRepository
from spetr.api.sse_broadcaster import SSEBroadcaster
from spetr.api.routes import setup_routes

UI_ASSETS_DIR = Path(__file__).parent.parent / "ui" / "assets"


def create_api_app(
    event_bus: Optional[IEventBus] = None,
    repository: Optional[IRepository] = None,
    broadcaster: Optional[SSEBroadcaster] = None
) -> FastAPI:
    app = FastAPI(
        title="SPETR Local API",
        docs_url="/docs",
        redoc_url=None
    )

    # Permite CORS para localhost e PyWebView
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if broadcaster is None:
        broadcaster = SSEBroadcaster(event_bus)

    # Registra rotas
    api_router = setup_routes(broadcaster, repository)
    app.include_router(api_router)

    # Rota raiz servindo o index.html da UI
    @app.get("/")
    async def serve_index():
        index_path = UI_ASSETS_DIR / "index.html"
        if index_path.exists():
            return FileResponse(index_path)
        return {"status": "SPETR running. UI index not found."}

    # Monta arquivos estáticos
    if UI_ASSETS_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(UI_ASSETS_DIR)), name="static")

    return app
