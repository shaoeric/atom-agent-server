"""Integration tests with Redis (skipped if connection fails)."""

from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio
import redis.asyncio as redis

from agent_backend.redis_store import RedisTaskStore
from agent_backend.tasks_execution import execute_task


async def _redis_ping(url: str) -> bool:
    try:
        r = redis.from_url(url, decode_responses=True)
        try:
            pong = await r.ping()
            return bool(pong)
        finally:
            await r.aclose()
    except Exception:
        return False


@pytest_asyncio.fixture
async def store(redis_url: str):
    ok = await _redis_ping(redis_url)
    if not ok:
        pytest.skip("Redis not available at " + redis_url)
    s = RedisTaskStore(redis_url, "agent:tasks:pending:test")
    await s.connect()
    await s.r.flushdb()
    yield s
    await s.r.flushdb()
    await s.close()


@pytest.mark.asyncio
@pytest.mark.redis
async def test_enqueue_and_events(store: RedisTaskStore):
    tid = await store.enqueue_task({"prompt": "hi", "mode": "mock"})
    meta = await store.get_meta(tid)
    assert meta.get("status") in ("queued",)
    evs = await store.replay_events(tid, 0)
    assert any(e.get("type") == "status" for e in evs)


@pytest.mark.asyncio
@pytest.mark.redis
async def test_execute_mock_short(store: RedisTaskStore):
    tid = str(uuid.uuid4())
    await execute_task(
        store,
        tid,
        {"prompt": "x", "mode": "mock", "steps": 3, "delay_s": 0.01},
    )
    meta = await store.get_meta(tid)
    assert meta.get("status") == "succeeded"
    evs = await store.replay_events(tid, 0)
    assert any(e.get("type") == "result" for e in evs)


@pytest.mark.asyncio
@pytest.mark.redis
async def test_50_concurrent_mock(store: RedisTaskStore):
    sem = asyncio.Semaphore(50)

    async def one(i: int) -> None:
        tid = str(uuid.uuid4())
        payload = {"prompt": f"p{i}", "mode": "mock", "steps": 5, "delay_s": 0.01}
        async with sem:
            await execute_task(store, tid, payload)

    await asyncio.gather(*[one(i) for i in range(50)])
