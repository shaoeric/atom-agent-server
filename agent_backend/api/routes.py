"""Task REST, SSE, and WebSocket."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from agent_backend.store_protocol import TaskStore

logger = logging.getLogger(__name__)

router = APIRouter(tags=["tasks"])


class TaskCreate(BaseModel):
    prompt: str = ""
    user_id: str | None = None
    #: 同一 ID 多次任务共享 ReAct 工作记忆；不传则每任务独立上下文。
    session_id: str | None = None
    mode: str | None = Field(
        default=None,
        description="mock | agent (default from MOCK_AGENT_DEFAULT)",
    )


def _store(request: Request) -> TaskStore:
    return request.app.state.store


@router.post("/tasks")
async def create_task(body: TaskCreate, request: Request) -> JSONResponse:
    store = _store(request)
    settings = request.app.state.settings
    mode = body.mode
    if mode is None:
        mode = "mock" if settings.mock_agent_default else "agent"
    payload: dict[str, Any] = {
        "prompt": body.prompt,
        "mode": mode,
    }
    if body.user_id:
        payload["user_id"] = body.user_id
    if body.session_id is not None and str(body.session_id).strip():
        payload["session_id"] = str(body.session_id).strip()
    task_id = await store.enqueue_task(payload)
    return JSONResponse({"task_id": task_id, "status": "queued"})


@router.get("/tasks/{task_id}")
async def get_task(task_id: str, request: Request) -> JSONResponse:
    store = _store(request)
    meta = await store.get_meta(task_id)
    if not meta:
        raise HTTPException(status_code=404, detail="task not found")
    return JSONResponse({"task_id": task_id, **meta})


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str, request: Request) -> JSONResponse:
    store = _store(request)
    meta = await store.get_meta(task_id)
    if not meta:
        raise HTTPException(status_code=404, detail="task not found")
    await store.request_cancel(task_id)
    return JSONResponse({"task_id": task_id, "cancel_requested": True})


async def _sse_stream(
    store: TaskStore,
    task_id: str,
    from_seq: int,
) -> Any:
    meta = await store.get_meta(task_id)
    if not meta:
        yield f"data: {json.dumps({'error': 'task not found'})}\n\n"
        return
    for ev in await store.replay_events(task_id, from_seq):
        yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        if ev.get("type") in ("result", "error"):
            return
    last = from_seq
    pubsub = await store.subscribe_live(task_id)
    try:
        while True:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=60.0,
            )
            if message is None:
                continue
            if message["type"] != "message":
                continue
            raw = message["data"]
            if isinstance(raw, bytes):
                raw = raw.decode()
            data = json.loads(raw)
            if data["seq"] > last:
                last = data["seq"]
                yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                if data.get("type") in ("result", "error"):
                    return
    except asyncio.CancelledError:
        raise
    finally:
        await pubsub.unsubscribe()
        await pubsub.aclose()


@router.get("/tasks/{task_id}/events")
async def task_events_sse(
    task_id: str,
    request: Request,
    from_seq: int = 0,
) -> StreamingResponse:
    store = _store(request)
    return StreamingResponse(
        _sse_stream(store, task_id, from_seq),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.websocket("/tasks/{task_id}/ws")
async def task_ws(ws: WebSocket, task_id: str) -> None:
    await ws.accept()
    store: TaskStore = ws.app.state.store
    meta = await store.get_meta(task_id)
    if not meta:
        await ws.send_json({"error": "task not found"})
        await ws.close()
        return
    from_seq = 0
    try:
        init = await asyncio.wait_for(ws.receive_json(), timeout=5.0)
        if isinstance(init, dict) and init.get("from_seq") is not None:
            from_seq = int(init["from_seq"])
    except WebSocketDisconnect:
        raise
    except (asyncio.TimeoutError, TypeError, ValueError, KeyError):
        from_seq = 0
    for ev in await store.replay_events(task_id, from_seq):
        await ws.send_json(ev)
        if ev.get("type") in ("result", "error"):
            await ws.close()
            return
    last = from_seq
    pubsub = await store.subscribe_live(task_id)
    try:
        while True:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=60.0,
            )
            if message is None:
                continue
            if message["type"] != "message":
                continue
            raw = message["data"]
            if isinstance(raw, bytes):
                raw = raw.decode()
            data = json.loads(raw)
            if data["seq"] > last:
                last = data["seq"]
                await ws.send_json(data)
                if data.get("type") in ("result", "error"):
                    await ws.close()
                    return
    except WebSocketDisconnect:
        logger.debug("ws disconnect %s", task_id)
    finally:
        await pubsub.unsubscribe()
        await pubsub.aclose()
