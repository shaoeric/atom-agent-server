"""In-memory store tests (no Redis)."""

from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio

from agent_backend.memory_store import InMemoryTaskStore
from agent_backend.tasks_execution import execute_task


@pytest_asyncio.fixture
async def store() -> InMemoryTaskStore:
    return InMemoryTaskStore()


@pytest.mark.asyncio
async def test_enqueue_replay(store: InMemoryTaskStore) -> None:
    tid = await store.enqueue_task({"prompt": "hi", "mode": "mock"})
    meta = await store.get_meta(tid)
    assert meta.get("status") == "queued"
    evs = await store.replay_events(tid, 0)
    assert any(e.get("type") == "status" for e in evs)


@pytest.mark.asyncio
async def test_execute_mock(store: InMemoryTaskStore) -> None:
    tid = str(uuid.uuid4())
    await execute_task(
        store,
        tid,
        {"prompt": "x", "mode": "mock", "steps": 3, "delay_s": 0.01},
    )
    meta = await store.get_meta(tid)
    assert meta.get("status") == "succeeded"


@pytest.mark.asyncio
async def test_queue_consume_worker_path(store: InMemoryTaskStore) -> None:
    """Task queue: enqueue puts one message; consume_task returns it."""
    tid = await store.enqueue_task({"prompt": "q", "mode": "mock"})
    item = await store.consume_task()
    assert item is not None
    delivery_id, fields = item
    assert fields["task_id"] == tid
    await store.ack_delivery(delivery_id)
