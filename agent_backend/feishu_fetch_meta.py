"""Parse ``lark-cli docs +fetch`` merged logs and build pagination hints for the agent."""

from __future__ import annotations

import json
import re
from typing import Any


def _stdout_payload(merged_log: str) -> str:
    """Rebuild stdout from ``run_cli_streaming`` merged ``[stdout]`` lines."""
    lines: list[str] = []
    for line in merged_log.splitlines():
        if line.startswith("[stdout] "):
            lines.append(line[len("[stdout] ") :])
    return "\n".join(lines).strip()


def parse_docs_fetch_json(merged_log: str) -> dict[str, Any] | None:
    """Best-effort parse JSON object from merged CLI log (stdout lines)."""
    raw = _stdout_payload(merged_log)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Single-line JSON embedded in noise
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    m = re.search(r"\{[\s\S]*\}", raw)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return None


def format_fetch_pagination_footer(
    *,
    merged_log: str,
    exit_code: int,
    offset: int,
    limit: int,
) -> str:
    """Append machine-readable pagination footer so the model does not stop after one page."""
    parsed = parse_docs_fetch_json(merged_log)
    lines = [
        "",
        "--- feishu_fetch_pagination (mandatory; do not ignore) ---",
        f"exit_code: {exit_code}",
        f"this_request: offset={offset} limit={limit}",
    ]
    if "truncated" in merged_log.lower():
        lines.append(
            "warning: output may be truncated; increase env LARK_DOC_FETCH_MAX_TOOL_CHARS if JSON is incomplete."
        )
    if parsed is None:
        lines.append("json_parse: failed; locate JSON in raw output above or retry with smaller limit.")
        lines.append("---")
        return "\n".join(lines)

    md = parsed.get("markdown")
    md_len = len(md) if isinstance(md, str) else 0
    lines.append(f"markdown_chars_this_page: {md_len}")

    hm = parsed.get("has_more")
    lines.append(f"has_more: {hm}")

    if hm is True:
        nxt = offset + limit
        lines.append(f"next_offset: {nxt}")
        lines.append(
            f"ACTION_REQUIRED: call feishu_fetch_doc again with same doc_url, offset={nxt}, limit={limit}"
        )
        lines.append(
            "Do NOT claim you only saw a short excerpt until has_more becomes false across all pages."
        )
    else:
        lines.append("pagination_done: true (no further pages for this doc with current API)")

    title = parsed.get("title")
    if title:
        lines.append(f"doc_title: {title}")

    lines.append(
        "Per-page review: you may call feishu_doc_comment for issues found in THIS page's markdown; "
        "selection_text must be copied verbatim from text visible on this page."
    )
    lines.append("---")
    return "\n".join(lines)
