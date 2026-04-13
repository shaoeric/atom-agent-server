"""In-process task queue + log + pub/sub (no Redis). For dev/tests or single-process API + embedded worker."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections import defaultdict
from typing import Any


class MemoryPubSub:
    """Redis pubsub-compatible subset for routes (get_message / unsubscribe / aclose)."""

    def __init__(
        self,
        task_id: str,
        queue: asyncio.Queue[str | None],
        unregister: Any,
    ) -> None:
        self._task_id = task_id
        self._queue = queue
        self._unregister = unregister
        self._closed = False

    async def get_message(
        self,
        ignore_subscribe_messages: bool = False,
        timeout: float | None = 60.0,
    ) -> dict[str, Any] | None:
        if self._closed:
            return None
        try:
            if timeout is None:
                raw = await self._queue.get()
            else:
                raw = await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None
        if raw is None:
            return None
        return {"type": "message", "data": raw}

    async def unsubscribe(self, *args: Any, **kwargs: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._unregister()


class InMemoryTaskStore:
    """Task queue: asyncio.Queue. Events: per-task list + fan-out to subscriber queues."""

    def __init__(self) -> None:
        self._pending: asyncio.Queue[tuple[str, dict[str, str]]] = asyncio.Queue()
        self._meta: dict[str, dict[str, str]] = {}
        self._logs: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._seq: dict[str, int] = {}
        self._cancel: set[str] = set()
        self._listeners: dict[str, list[asyncio.Queue[str | None]]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        return

    async def close(self) -> None:
        return

    async def enqueue_task(
        self,
        payload: dict[str, Any],
        task_id: str | None = None,
    ) -> str:
        tid = task_id or str(uuid.uuid4())
        ts = str(int(time.time()))
        msg_id = f"mem-{uuid.uuid4()}"
        async with self._lock:
            self._meta[tid] = {
                "status": "queued",
                "created_at": ts,
                "updated_at": ts,
                "payload": json.dumps(payload, ensure_ascii=False),
            }
            self._seq[tid] = 0
        await self._pending.put(
            (msg_id, {"task_id": tid, "payload": json.dumps(payload, ensure_ascii=False)}),
        )
        # append_event uses its own lock; must not run under enqueue_task's lock
        await self.append_event(tid, "status", chunk="queued", meta={"task_id": tid})
        return tid

    async def update_meta(
        self,
        task_id: str,
        *,
        status: str | None = None,
        extra: dict[str, str] | None = None,
    ) -> None:
        ts = str(int(time.time()))
        async with self._lock:
            m = self._meta.setdefault(task_id, {})
            m["updated_at"] = ts
            if status:
                m["status"] = status
            if extra:
                m.update(extra)

    async def get_meta(self, task_id: str) -> dict[str, str]:
        async with self._lock:
            return dict(self._meta.get(task_id, {}))

    def _fanout(self, task_id: str, data: str) -> None:
        for q in list(self._listeners.get(task_id, [])):
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                pass

    async def append_event(
        self,
        task_id: str,
        event_type: str,
        *,
        chunk: str = "",
        meta: dict[str, Any] | None = None,
    ) -> int:
        async with self._lock:
            self._seq[task_id] = self._seq.get(task_id, 0) + 1
            seq = self._seq[task_id]
            ev = {"seq": seq, "type": event_type, "chunk": chunk, "meta": meta or {}}
            self._logs[task_id].append(ev)
            data = json.dumps(ev, ensure_ascii=False)
        self._fanout(task_id, data)
        return seq

    async def is_cancelled(self, task_id: str) -> bool:
        async with self._lock:
            return task_id in self._cancel

    async def request_cancel(self, task_id: str) -> None:
        async with self._lock:
            self._cancel.add(task_id)
        await self.append_event(
            task_id,
            "status",
            chunk="cancel_requested",
            meta={},
        )

    async def replay_events(self, task_id: str, from_seq: int) -> list[dict[str, Any]]:
        async with self._lock:
            logs = list(self._logs.get(task_id, []))
        out = [e for e in logs if e["seq"] > from_seq]
        out.sort(key=lambda x: x["seq"])
        return out

    async def subscribe_live(self, task_id: str) -> MemoryPubSub:
        q: asyncio.Queue[str | None] = asyncio.Queue(maxsize=4096)

        def unregister() -> None:
            lst = self._listeners.get(task_id)
            if lst and q in lst:
                lst.remove(q)

        self._listeners[task_id].append(q)
        return MemoryPubSub(task_id, q, unregister)

    async def consume_task(self) -> tuple[str, dict[str, str]] | None:
        try:
            return await asyncio.wait_for(self._pending.get(), timeout=5.0)
        except asyncio.TimeoutError:
            return None

    async def ack_delivery(self, _delivery_id: str) -> None:
        return

    async def ensure_worker_ready(self) -> None:
        return
