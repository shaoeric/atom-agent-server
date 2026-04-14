"""Abstract task store: queue + task metadata + append-only log + live fan-out."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class TaskStore(Protocol):
    """Queue: enqueue -> consume_task (worker). Log: append_event + replay + live."""

    async def connect(self) -> None: ...

    async def close(self) -> None: ...

    async def enqueue_task(
        self,
        payload: dict[str, Any],
        task_id: str | None = None,
    ) -> str: ...

    async def update_meta(
        self,
        task_id: str,
        *,
        status: str | None = None,
        extra: dict[str, str] | None = None,
    ) -> None: ...

    async def get_meta(self, task_id: str) -> dict[str, str]: ...

    async def append_event(
        self,
        task_id: str,
        event_type: str,
        *,
        chunk: str = "",
        meta: dict[str, Any] | None = None,
    ) -> int: ...

    async def is_cancelled(self, task_id: str) -> bool: ...

    async def request_cancel(self, task_id: str) -> None: ...

    async def replay_events(self, task_id: str, from_seq: int) -> list[dict[str, Any]]: ...

    async def subscribe_live(self, task_id: str) -> Any: ...

    async def consume_task(self) -> tuple[str, dict[str, str]] | None:
        """Block until one queued task or timeout; return (delivery_id, fields) or None."""
        ...

    async def ack_delivery(self, delivery_id: str) -> None:
        """Acknowledge a consumed queue message (no-op for in-memory)."""
        ...

    async def ensure_worker_ready(self) -> None:
        """Redis: create consumer group. Memory: no-op."""
        ...

    async def session_get(self, storage_key: str) -> str | None:
        """Read persisted session JSON (multi-turn agent memory)."""
        ...

    async def session_set(
        self,
        storage_key: str,
        value: str,
        *,
        ttl_seconds: int | None = None,
    ) -> None:
        """Write session JSON; optional TTL for Redis."""
        ...
