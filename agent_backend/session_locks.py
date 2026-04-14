"""Per-session asyncio locks so concurrent tasks for the same session_id do not corrupt memory."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

_locks: dict[str, asyncio.Lock] = {}
_registry_lock = asyncio.Lock()


@asynccontextmanager
async def session_lock(session_id: str) -> AsyncIterator[None]:
    async with _registry_lock:
        if session_id not in _locks:
            _locks[session_id] = asyncio.Lock()
        lock = _locks[session_id]
    async with lock:
        yield None
