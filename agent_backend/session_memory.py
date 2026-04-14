"""Persist AgentScope InMemoryMemory across tasks (multi-turn); merges _compressed_summary."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from agentscope.memory import InMemoryMemory

from agent_backend.config import get_settings

if TYPE_CHECKING:
    from agent_backend.store_protocol import TaskStore


def session_storage_key(user_id: str, session_id: str) -> str:
    return f"agent:session:{user_id}:{session_id}:agentscope_memory"


def memory_to_snapshot(memory: InMemoryMemory) -> dict:
    """InMemoryMemory.state_dict() omits _compressed_summary; merge for persistence."""
    return {
        "content": memory.state_dict()["content"],
        "_compressed_summary": memory._compressed_summary,
    }


async def load_session_memory(
    store: "TaskStore",
    user_id: str,
    session_id: str | None,
) -> InMemoryMemory:
    if not session_id:
        return InMemoryMemory()
    raw = await store.session_get(session_storage_key(user_id, session_id))
    if not raw:
        return InMemoryMemory()
    data = json.loads(raw)
    memory = InMemoryMemory()
    memory.load_state_dict({"content": data.get("content", [])}, strict=False)
    summary = data.get("_compressed_summary") or ""
    if summary:
        await memory.update_compressed_summary(summary)
    return memory


async def save_session_memory(
    store: "TaskStore",
    user_id: str,
    session_id: str | None,
    memory: InMemoryMemory,
) -> None:
    if not session_id:
        return
    snapshot = memory_to_snapshot(memory)
    settings = get_settings()
    await store.session_set(
        session_storage_key(user_id, session_id),
        json.dumps(snapshot, ensure_ascii=False),
        ttl_seconds=settings.session_ttl_seconds,
    )
