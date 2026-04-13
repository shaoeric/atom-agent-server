"""Bridge worker queue payload to mock or agent runner."""

from __future__ import annotations

import json
import logging
from typing import Any

from agent_backend.agent_runner import run_mock_task, run_react_agent_task
from agent_backend.store import RedisTaskStore

logger = logging.getLogger(__name__)


async def execute_task(
    store: RedisTaskStore,
    task_id: str,
    payload: dict[str, Any],
) -> None:
    mode = (payload.get("mode") or "mock").lower()
    prompt = str(payload.get("prompt") or "")
    try:
        if mode == "mock":
            await run_mock_task(
                store,
                task_id,
                prompt,
                steps=int(payload.get("steps", 30)),
                delay_s=float(payload.get("delay_s", 0.05)),
            )
        elif mode == "agent":
            await run_react_agent_task(store, task_id, prompt)
        else:
            await store.append_event(
                task_id,
                "error",
                chunk=f"unknown mode: {mode}",
                meta={},
            )
            await store.update_meta(task_id, status="failed")
    except Exception as e:
        logger.exception("task %s failed", task_id)
        await store.append_event(
            task_id,
            "error",
            chunk=str(e),
            meta={"type": type(e).__name__},
        )
        await store.update_meta(task_id, status="failed")


def payload_from_raw(raw: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    return json.loads(raw)
