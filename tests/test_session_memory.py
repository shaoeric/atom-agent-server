"""Session memory persistence (InMemoryMemory + _compressed_summary)."""

import json

import pytest
import pytest_asyncio
from agentscope.memory import InMemoryMemory
from agentscope.message import Msg

from agent_backend.memory_store import InMemoryTaskStore
from agent_backend.session_memory import (
    load_session_memory,
    memory_to_snapshot,
    save_session_memory,
    session_storage_key,
)


@pytest_asyncio.fixture
async def store() -> InMemoryTaskStore:
    return InMemoryTaskStore()


def test_session_storage_key() -> None:
    assert "u1" in session_storage_key("u1", "s1")
    assert "s1" in session_storage_key("u1", "s1")


@pytest.mark.asyncio
async def test_load_empty_session_returns_fresh_memory(store: InMemoryTaskStore) -> None:
    m = await load_session_memory(store, "u", None)
    assert await m.size() == 0


@pytest.mark.asyncio
async def test_roundtrip_compressed_summary(store: InMemoryTaskStore) -> None:
    mem = InMemoryMemory()
    await mem.add(Msg("user", "hi", "user"))
    await mem.update_compressed_summary("summary text")

    await save_session_memory(store, "user-a", "sess-1", mem)

    key = session_storage_key("user-a", "sess-1")
    raw = await store.session_get(key)
    assert raw is not None
    data = json.loads(raw)
    assert data["_compressed_summary"] == "summary text"
    assert len(data["content"]) >= 1

    loaded = await load_session_memory(store, "user-a", "sess-1")
    assert loaded._compressed_summary == "summary text"
    assert await loaded.size() >= 1


def test_memory_to_snapshot_includes_summary() -> None:
    m = InMemoryMemory()
    snap = memory_to_snapshot(m)
    assert "content" in snap
    assert "_compressed_summary" in snap
