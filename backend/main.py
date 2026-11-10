"""FastAPI application factory and lifecycle management."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from backend.agent.graph import build_graph
from backend.api.routes_chat import router as chat_router
from backend.api.routes_health import router as health_router
from backend.api.routes_undo import router as undo_router
from backend.config import get_settings
from backend.excel.com_thread import com_thread
from backend.excel.xlwings_adapter import XlwingsAdapter
from backend.logging_setup import configure_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan context manager."""
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "logs").mkdir(parents=True, exist_ok=True)
    configure_logging(settings)
    logger.info("Excel AI backend starting up on machine: %s", settings.machine_name)

    if not hasattr(app.state, "adapter") or app.state.adapter is None:
        app.state.adapter = XlwingsAdapter()

    checkpoints_path = settings.data_dir / "checkpoints.sqlite"
    if not hasattr(app.state, "graph") or app.state.graph is None:
        async with AsyncSqliteSaver.from_conn_string(str(checkpoints_path)) as checkpointer:
            app.state.graph = build_graph(checkpointer)
            yield
    else:
        yield

    logger.info("Excel AI backend shutting down")
    com_thread.shutdown()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application instance."""
    app = FastAPI(
        title="Excel AI",
        lifespan=lifespan,
    )

    # API routes with prefix /api
    app.include_router(health_router, prefix="/api")
    app.include_router(chat_router, prefix="/api")
    app.include_router(undo_router, prefix="/api")

    # Static files mounted at root AFTER API routers to prevent shadowing
    frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
    if frontend_dir.exists():
        app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")

    return app
