"""Select Redis or in-memory task store from settings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent_backend.memory_store import InMemoryTaskStore
from agent_backend.redis_store import RedisTaskStore
from agent_backend.store_protocol import TaskStore

if TYPE_CHECKING:
    from agent_backend.config import Settings

_memory_singleton: InMemoryTaskStore | None = None


def create_store(settings: "Settings") -> TaskStore:
    """Default backend is in-memory (see Settings.store_backend)."""
    global _memory_singleton
    if settings.store_backend == "memory":
        if _memory_singleton is None:
            _memory_singleton = InMemoryTaskStore()
        return _memory_singleton
    return RedisTaskStore(
        settings.redis_url,
        task_stream_key=settings.task_stream_key,
        consumer_group=settings.consumer_group,
        consumer_name=settings.consumer_name,
    )


def reset_memory_store_for_tests() -> None:
    """Clear singleton so tests get a fresh queue."""
    global _memory_singleton
    _memory_singleton = None
