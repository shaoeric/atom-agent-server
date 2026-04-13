"""Async subprocess CLI execution with line-based streaming to task log events."""

from __future__ import annotations

import asyncio
import os
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_backend.store_protocol import TaskStore

# 工具返回给 LLM 的合并日志最大长度（仍可通过 SSE 看完整流式事件）
_DEFAULT_MAX_TOOL_CHARS = 12000


async def _read_lines(
    stream: asyncio.StreamReader | None,
    task_id: str,
    store: "TaskStore",
    stream_name: str,
    capture: list[str] | None = None,
) -> None:
    if stream is None:
        return
    while True:
        line = await stream.readline()
        if not line:
            break
        text = line.decode(errors="replace").rstrip("\n\r")
        if text:
            await store.append_event(task_id, stream_name, chunk=text)
            if capture is not None:
                capture.append(f"[{stream_name}] {text}")


def _truncate_for_tool(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 32] + "\n... [truncated for tool response]"


async def run_cli_streaming(
    store: "TaskStore",
    task_id: str,
    argv: list[str],
    *,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    max_tool_chars: int = _DEFAULT_MAX_TOOL_CHARS,
) -> tuple[int, str]:
    """Run argv[0] with argv[1:].

    - 仍按行写入 store（stdout/stderr 事件），供 SSE 订阅。
    - 同时合并为一段文本返回，供 ToolResponse 给 LLM 阅读。

    Returns:
        (exit_code, captured_log)  ``captured_log`` 可能因 ``max_tool_chars`` 被截断。
    """
    if not argv:
        raise ValueError("argv must not be empty")
    exec_env = {**os.environ, **(env or {})}
    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(asyncio.subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=cwd,
        env=exec_env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        creationflags=creationflags,
    )
    assert proc.stdout and proc.stderr
    captured: list[str] = []
    await asyncio.gather(
        _read_lines(proc.stdout, task_id, store, "stdout", captured),
        _read_lines(proc.stderr, task_id, store, "stderr", captured),
    )
    code = int(await proc.wait())
    merged = "\n".join(captured)
    merged = _truncate_for_tool(merged, max_tool_chars)
    return code, merged


async def terminate_process_tree(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return
    if sys.platform == "win32":
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=10)
        except TimeoutError:
            proc.kill()
    else:
        try:
            import signal

            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError, AttributeError):
            proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=10)
        except TimeoutError:
            proc.kill()
