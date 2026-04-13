"""AgentScope ReActAgent execution with optional CLI tool and mock mode."""

from __future__ import annotations

import asyncio
import json
import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent_backend.store import RedisTaskStore


async def run_mock_task(
    store: "RedisTaskStore",
    task_id: str,
    prompt: str,
    *,
    steps: int = 30,
    delay_s: float = 0.05,
    **_: Any,
) -> None:
    """Long-running fake task for load tests (no LLM)."""
    await store.update_meta(task_id, status="running")
    await store.append_event(
        task_id,
        "status",
        chunk="mock_running",
        meta={"prompt_preview": prompt[:120]},
    )
    for i in range(steps):
        if await store.is_cancelled(task_id):
            await store.append_event(task_id, "result", meta={"cancelled": True})
            await store.update_meta(task_id, status="cancelled")
            return
        await asyncio.sleep(delay_s)
        await store.append_event(task_id, "agent", chunk=f"mock_step_{i}")
    await store.append_event(task_id, "result", meta={"ok": True, "mode": "mock"})
    await store.update_meta(task_id, status="succeeded")


def _msg_to_text(msg: Any) -> str:
    content = getattr(msg, "content", None)
    if content is None:
        return str(msg)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if hasattr(block, "text"):
                parts.append(str(block.text))
            else:
                parts.append(str(block))
        return "\n".join(parts)
    return str(content)


async def run_react_agent_task(
    store: "RedisTaskStore",
    task_id: str,
    prompt: str,
    *,
    enable_cli_tool: bool = True,
) -> None:
    """Run ReActAgent with streaming; requires DASHSCOPE_API_KEY for DashScope."""
    await store.update_meta(task_id, status="running")
    api_key = os.environ.get("DASHSCOPE_API_KEY")
    if not api_key:
        await store.append_event(
            task_id,
            "error",
            chunk="DASHSCOPE_API_KEY not set; refusing agent mode",
            meta={},
        )
        await store.update_meta(task_id, status="failed")
        return

    from agentscope.agent import ReActAgent
    from agentscope.formatter import DashScopeChatFormatter
    from agentscope.memory import InMemoryMemory
    from agentscope.message import Msg, TextBlock
    from agentscope.model import DashScopeChatModel
    from agentscope.pipeline import stream_printing_messages
    from agentscope.tool import Toolkit, ToolResponse

    from agent_backend.cli_runner import run_cli_streaming

    toolkit = Toolkit()
    if enable_cli_tool:

        async def cli_exec(command: str) -> ToolResponse:
            """Execute a shell command; streams stdout/stderr to task log, returns short summary."""
            parts = command.strip().split()
            if not parts:
                return ToolResponse(content=[TextBlock(type="text", text="empty command")])
            await store.append_event(task_id, "status", chunk=f"cli_start: {command[:200]}")
            code = await run_cli_streaming(store, task_id, parts)
            summary = f"exit_code={code}"
            await store.append_event(task_id, "status", chunk=f"cli_end: {summary}")
            return ToolResponse(content=[TextBlock(type="text", text=summary)])

    model = DashScopeChatModel(
        "qwen-turbo",
        api_key=api_key,
        stream=True,
    )
    agent = ReActAgent(
        name="backend_agent",
        sys_prompt="You are a helpful assistant. Use cli_exec for shell commands when needed.",
        model=model,
        formatter=DashScopeChatFormatter(),
        toolkit=toolkit,
        memory=InMemoryMemory(),
    )

    async def agent_coroutine():
        return await agent(Msg("user", prompt))

    try:
        async for msg, _last in stream_printing_messages([agent], agent_coroutine()):
            text = _msg_to_text(msg)
            if text:
                await store.append_event(task_id, "agent", chunk=text)
    except Exception as e:
        await store.append_event(
            task_id,
            "error",
            chunk=str(e),
            meta={"type": type(e).__name__},
        )
        await store.update_meta(task_id, status="failed")
        return

    await store.append_event(task_id, "result", meta={"ok": True, "mode": "agent"})
    await store.update_meta(task_id, status="succeeded")
