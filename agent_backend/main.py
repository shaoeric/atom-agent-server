"""FastAPI entry: task API, SSE, WebSocket; optional embedded in-memory worker."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from agent_backend.api.routes import router as task_router
from agent_backend.config import get_settings
from agent_backend.factory import create_store
from agent_backend.worker import worker_loop


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    store = create_store(settings)
    await store.connect()
    app.state.store = store
    app.state.settings = settings
    worker_task: asyncio.Task | None = None
    if settings.store_backend == "memory" and settings.embed_worker:
        worker_task = asyncio.create_task(worker_loop(settings=settings, store=store))
        app.state._worker_task = worker_task
    yield
    if worker_task is not None:
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
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
        s = get_settings()
        return {
            "status": "ok",
            "store_backend": s.store_backend,
            "embed_worker": s.embed_worker,
        }

    return app


app = create_app()
