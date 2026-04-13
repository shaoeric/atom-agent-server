"""FastAPI entry: task API, SSE, WebSocket."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from agent_backend.api.routes import router as task_router
from agent_backend.config import get_settings
from agent_backend.store import RedisTaskStore


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    store = RedisTaskStore(settings.redis_url, settings.task_stream_key)
    await store.connect()
    app.state.store = store
    app.state.settings = settings
    yield
    await store.close()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Agent Backend",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(task_router, prefix="/api/v1")

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
