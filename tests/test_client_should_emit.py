"""Tests for client SSE display filtering."""

import client


def test_should_emit_non_agent_always() -> None:
    assert client._should_emit_event(
        {"type": "status", "chunk": "x"},
        only_final_agent_chunks=True,
    )


def test_should_emit_agent_intermediate_skipped_when_only_final() -> None:
    assert not client._should_emit_event(
        {"type": "agent", "meta": {"is_final_chunk": False}},
        only_final_agent_chunks=True,
    )


def test_should_emit_agent_final_when_only_final() -> None:
    assert client._should_emit_event(
        {"type": "agent", "meta": {"is_final_chunk": True}},
        only_final_agent_chunks=True,
    )


def test_legacy_agent_event_without_meta_treated_as_final() -> None:
    assert client._should_emit_event(
        {"type": "agent", "chunk": "x"},
        only_final_agent_chunks=True,
    )


def test_stream_mode_shows_all_agent_chunks() -> None:
    assert client._should_emit_event(
        {"type": "agent", "meta": {"is_final_chunk": False}},
        only_final_agent_chunks=False,
    )
