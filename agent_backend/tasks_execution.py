"""Bridge worker queue payload to mock or agent runner."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from agent_backend.agent_runner import run_mock_task, run_react_agent_task

if TYPE_CHECKING:
    from agent_backend.store_protocol import TaskStore


async def execute_task(
    store: "TaskStore",
    task_id: str,
    payload: dict[str, Any],
) -> None:
    mode = (payload.get("mode") or "mock").lower()
    prompt = str(payload.get("prompt") or "")
    if mode == "mock":
        await run_mock_task(
            store,
            task_id,
            prompt,
            steps=int(payload.get("steps", 30)),
            delay_s=float(payload.get("delay_s", 0.05)),
        )
    elif mode == "agent":
        raw_sid = payload.get("session_id")
        session_id: str | None = None
        if raw_sid is not None:
            s = str(raw_sid).strip()
            if s:
                session_id = s
        user_id = str(payload.get("user_id") or "default")
        await run_react_agent_task(
            store,
            task_id,
            prompt,
            session_id=session_id,
            user_id=user_id,
        )
    else:
        await store.append_event(
            task_id,
            "error",
            chunk=f"unknown mode: {mode}",
            meta={},
        )
        await store.update_meta(task_id, status="failed")


def payload_from_raw(raw: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    return json.loads(raw)
