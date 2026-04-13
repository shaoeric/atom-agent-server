"""50-way concurrent mock execution (requires Redis)."""

from __future__ import annotations

import asyncio
import uuid

import pytest
import redis.asyncio as redis

from agent_backend.redis_store import RedisTaskStore
from agent_backend.tasks_execution import execute_task


async def _redis_ping(url: str) -> bool:
    try:
        r = redis.from_url(url, decode_responses=True)
        try:
            return bool(await r.ping())
        finally:
            await r.aclose()
    except Exception:
        return False


@pytest.mark.asyncio
@pytest.mark.redis
async def test_50_concurrent_mock_load(redis_url: str):
    if not await _redis_ping(redis_url):
        pytest.skip("Redis not available")
    store = RedisTaskStore(redis_url, "agent:tasks:pending:loadtest")
    await store.connect()
    await store.r.flushdb()
    try:
        sem = asyncio.Semaphore(50)

        async def run_one() -> str:
            tid = str(uuid.uuid4())
            payload = {
                "prompt": "load",
                "mode": "mock",
                "steps": 8,
                "delay_s": 0.02,
            }
            async with sem:
                await execute_task(store, tid, payload)
            return tid

        ids = await asyncio.gather(*[run_one() for _ in range(50)])
        assert len(set(ids)) == 50
        for tid in ids[:5]:
            meta = await store.get_meta(tid)
            assert meta.get("status") == "succeeded"
    finally:
        await store.r.flushdb()
        await store.close()
