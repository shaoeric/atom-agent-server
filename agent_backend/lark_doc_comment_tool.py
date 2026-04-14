"""Build ``lark-cli drive +add-comment`` argv for Feishu doc comments (full or selection)."""

from __future__ import annotations

import json
from typing import Literal


def build_reply_elements_json(comment_text: str) -> str:
    return json.dumps([{"type": "text", "text": comment_text}], ensure_ascii=False)


CommentMode = Literal["full", "selection", "block_id"]


def build_add_comment_argv(
    *,
    lark_cli: str,
    doc: str,
    comment_text: str,
    mode: CommentMode,
    selection_text: str = "",
    block_id: str = "",
    dry_run: bool = False,
) -> list[str]:
    """Return argv for ``lark-cli`` (no shell), suitable for ``asyncio.create_subprocess_exec``."""
    content = build_reply_elements_json(comment_text)
    cmd: list[str] = [
        lark_cli,
        "drive",
        "+add-comment",
        "--doc",
        doc,
        "--content",
        content,
    ]
    if mode == "full":
        cmd.append("--full-comment")
    elif mode == "selection":
        sel = selection_text.strip()
        if not sel:
            raise ValueError("selection_text is required when mode is selection")
        cmd.extend(["--selection-with-ellipsis", sel])
    elif mode == "block_id":
        bid = block_id.strip()
        if not bid:
            raise ValueError("block_id is required when mode is block_id")
        cmd.extend(["--block-id", bid])
    else:
        raise ValueError(f"invalid mode: {mode!r}")
    if dry_run:
        cmd.append("--dry-run")
    return cmd
