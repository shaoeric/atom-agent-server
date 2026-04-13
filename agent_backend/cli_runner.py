"""Async subprocess CLI execution with line-based streaming to task log events."""

from __future__ import annotations

import asyncio
import os
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_backend.store_protocol import TaskStore


async def _read_lines(
    stream: asyncio.StreamReader | None,
    task_id: str,
    store: "TaskStore",
    stream_name: str,
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


async def run_cli_streaming(
    store: "TaskStore",
    task_id: str,
    argv: list[str],
    *,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
) -> int:
    """Run argv[0] with argv[1:]; stream stdout/stderr as events. Return exit code."""
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
    await asyncio.gather(
        _read_lines(proc.stdout, task_id, store, "stdout"),
        _read_lines(proc.stderr, task_id, store, "stderr"),
    )
    return int(await proc.wait())


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
