"""Tests for feishu docs +fetch pagination footer."""

from agent_backend.feishu_fetch_meta import format_fetch_pagination_footer, parse_docs_fetch_json


def test_parse_merged_stdout_json() -> None:
    merged = """[stdout] {"title":"T","markdown":"abc","has_more":true}
[stderr] """
    d = parse_docs_fetch_json(merged)
    assert d is not None
    assert d["title"] == "T"
    assert d["has_more"] is True


def test_footer_has_more_shows_next_offset() -> None:
    merged = '[stdout] {"markdown":"hello","has_more":true}'
    foot = format_fetch_pagination_footer(
        merged_log=merged,
        exit_code=0,
        offset=0,
        limit=400,
    )
    assert "has_more: True" in foot
    assert "next_offset: 400" in foot
    assert "offset=400" in foot


def test_footer_done_no_next() -> None:
    merged = '[stdout] {"markdown":"x","has_more":false}'
    foot = format_fetch_pagination_footer(
        merged_log=merged,
        exit_code=0,
        offset=400,
        limit=400,
    )
    assert "pagination_done: true" in foot
