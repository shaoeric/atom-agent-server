"""AgentScope ReActAgent execution with optional CLI tool and mock mode."""

from __future__ import annotations

import asyncio
import os
import shlex
import shutil
import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent_backend.store_protocol import TaskStore


async def run_mock_task(
    store: "TaskStore",
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


def _resolve_lark_cli_binary(lark_cli_path: str) -> str | None:
    """Return absolute path to ``lark-cli``, or None if not found."""
    raw = (lark_cli_path or "").strip()
    if raw:
        return shutil.which(raw) or (raw if os.path.isfile(raw) else None)
    return shutil.which("lark-cli")


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
    store: "TaskStore",
    task_id: str,
    prompt: str,
    *,
    enable_cli_tool: bool = True,
    session_id: str | None = None,
    user_id: str = "default",
) -> None:
    """Run ReActAgent with streaming; OpenAI-compatible API (custom base_url supported)."""
    from agent_backend.config import get_settings

    await store.update_meta(task_id, status="running")
    settings = get_settings()
    api_key = settings.openai_api_key or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        await store.append_event(
            task_id,
            "error",
            chunk="OPENAI_API_KEY not set; refusing agent mode",
            meta={},
        )
        await store.update_meta(task_id, status="failed")
        return

    if session_id:
        await store.update_meta(
            task_id,
            extra={"session_id": session_id, "user_id": user_id},
        )

    from agentscope.agent import ReActAgent
    from agentscope.formatter import OpenAIChatFormatter
    from agentscope.memory import InMemoryMemory
    from agentscope.message import Msg, TextBlock
    from agentscope.model import OpenAIChatModel
    from agentscope.pipeline import stream_printing_messages
    from agentscope.token import OpenAITokenCounter
    from agentscope.tool import Toolkit, ToolResponse

    from agent_backend.cli_runner import run_cli_streaming
    from agent_backend.feishu_fetch_meta import format_fetch_pagination_footer
    from agent_backend.lark_doc_comment_tool import CommentMode, build_add_comment_argv
    from agent_backend.session_locks import session_lock
    from agent_backend.session_memory import load_session_memory, save_session_memory

    toolkit = Toolkit()
    if enable_cli_tool:

        async def cli_exec(command: str) -> ToolResponse:
            """Example: run packaged demo_cli."""
            parts = shlex.split(command.strip()) if command.strip() else []
            if not parts:
                return ToolResponse(
                    content=[TextBlock(type="text", text="empty command")],
                )
            argv = [
                sys.executable,
                "-m",
                "agent_backend.examples.demo_cli",
                *parts,
            ]
            await store.append_event(
                task_id,
                "status",
                chunk=f"cli_start: {' '.join(parts)}",
            )
            code, cli_log = await run_cli_streaming(store, task_id, argv)
            if cli_log:
                summary = f"exit_code={code}\n--- cli output (for model) ---\n{cli_log}"
            else:
                summary = f"exit_code={code}\n(no stdout/stderr lines)"
            await store.append_event(
                task_id,
                "status",
                chunk=f"cli_end: exit_code={code}",
            )
            return ToolResponse(content=[TextBlock(type="text", text=summary)])

        toolkit.register_tool_function(cli_exec)

    if settings.enable_lark_cli_tool:

        async def lark_cli_exec(command: str) -> ToolResponse:
            """Run the official Lark/Feishu CLI (lark-cli from github.com/larksuite/cli).

            Requires: npm install -g @larksuite/cli, and ``lark-cli config init`` / ``lark-cli auth login``.
            Pass only the arguments after ``lark-cli``, e.g. ``auth status``, ``calendar +agenda --format json``.
            """
            lark_bin = _resolve_lark_cli_binary(settings.lark_cli_path)
            if not lark_bin:
                return ToolResponse(
                    content=[
                        TextBlock(
                            type="text",
                            text=(
                                "lark-cli not found on PATH. Install: npm install -g @larksuite/cli "
                                "and ensure `lark-cli` is available, or set LARK_CLI_PATH to the executable."
                            ),
                        ),
                    ],
                )
            parts = shlex.split(command.strip(), posix=sys.platform != "win32")
            if not parts:
                return ToolResponse(
                    content=[TextBlock(type="text", text="empty command")],
                )
            argv: list[str] = [lark_bin, *parts]
            await store.append_event(
                task_id,
                "status",
                chunk=f"lark_cli_start: {' '.join(parts)}",
            )
            code, cli_log = await run_cli_streaming(store, task_id, argv)
            if cli_log:
                summary = f"exit_code={code}\n--- lark-cli output ---\n{cli_log}"
            else:
                summary = f"exit_code={code}\n(no stdout/stderr lines)"
            await store.append_event(
                task_id,
                "status",
                chunk=f"lark_cli_end: exit_code={code}",
            )
            return ToolResponse(content=[TextBlock(type="text", text=summary)])

        toolkit.register_tool_function(lark_cli_exec)

        async def feishu_fetch_doc(
            doc_url: str,
            offset: int = 0,
            limit: int | None = None,
        ) -> ToolResponse:
            """拉取飞书云文档正文一页（``lark-cli docs +fetch``）。长文档必须**分页多次调用**直到 ``has_more`` 为 false。

            工具返回末尾含 ``--- feishu_fetch_pagination ---``：其中有 ``has_more``、``next_offset`` 与
            ``markdown_chars_this_page``。若 ``has_more`` 为 true，必须用相同 ``doc_url``、
            ``offset=next_offset``、相同 ``limit`` 继续调用，**禁止**在未读完所有页时声称「只能看到摘要」。

            划词评论：每一页内单独分析；``selection_text`` 必须从**当前页** markdown 中逐字拷贝。

            Args:
                doc_url: 文档 URL 或 token（支持 docx、wiki 等，与 lark-cli 一致）。
                offset: 分页偏移（默认 0）。
                limit: 分页大小；默认取配置 ``LARK_DOC_FETCH_DEFAULT_LIMIT``（约 400）。
            """
            lark_bin = _resolve_lark_cli_binary(settings.lark_cli_path)
            if not lark_bin:
                return ToolResponse(
                    content=[
                        TextBlock(
                            type="text",
                            text=(
                                "lark-cli not found. Install @larksuite/cli and set LARK_CLI_PATH if needed."
                            ),
                        ),
                    ],
                )
            lim = int(limit) if limit is not None else settings.lark_doc_fetch_default_limit
            argv: list[str] = [
                lark_bin,
                "docs",
                "+fetch",
                "--doc",
                doc_url.strip(),
                "--offset",
                str(int(offset)),
                "--limit",
                str(lim),
            ]
            await store.append_event(
                task_id,
                "status",
                chunk=f"feishu_fetch_doc: offset={offset} limit={lim}",
            )
            code, cli_log = await run_cli_streaming(
                store,
                task_id,
                argv,
                max_tool_chars=settings.lark_doc_fetch_max_tool_chars,
            )
            if cli_log:
                summary = f"exit_code={code}\n--- docs +fetch ---\n{cli_log}"
            else:
                summary = f"exit_code={code}\n(no stdout/stderr lines)"
            summary += format_fetch_pagination_footer(
                merged_log=cli_log or "",
                exit_code=code,
                offset=int(offset),
                limit=lim,
            )
            await store.append_event(
                task_id,
                "status",
                chunk=f"feishu_fetch_doc_end: exit_code={code}",
            )
            return ToolResponse(content=[TextBlock(type="text", text=summary)])

        toolkit.register_tool_function(feishu_fetch_doc)

        async def feishu_doc_comment(
            doc_url: str,
            comment_text: str,
            comment_type: str = "selection",
            selection_text: str = "",
            block_id: str = "",
            dry_run: bool = False,
        ) -> ToolResponse:
            """在飞书云文档上添加评论（全文评审或划词评论），通过 ``lark-cli drive +add-comment``。

            划词批注时：``comment_text`` 应由你根据通读全文后的分析**自行撰写**（用户不必提供批注文案）。
            ``selection_text`` 必须是文档正文中**真实存在**且能被 locate-doc **唯一匹配**的片段；
            若短语重复出现，使用 ``开头...结尾`` 形式收窄范围（与 lark-cli 一致）。

            划词评论仅适用于新版 docx（或 wiki 解析为 docx）；旧版 doc 请用 ``comment_type="full"``。

            Args:
                doc_url: 文档链接或 token（docx / doc / wiki URL）。
                comment_text: 评论正文（纯文本，由模型撰写）。
                comment_type: ``full``=全文评论；``selection``=划词（需提供 ``selection_text``）；
                    ``block_id``=已知块 ID 时锚定（需提供 ``block_id``）。
                selection_text: ``selection`` 模式下的定位串，可为短句或 ``开头...结尾``。
                block_id: ``block_id`` 模式下的块 ID。
                dry_run: 为 True 时仅预览请求，不真正发送评论。
            """
            lark_bin = _resolve_lark_cli_binary(settings.lark_cli_path)
            if not lark_bin:
                return ToolResponse(
                    content=[
                        TextBlock(
                            type="text",
                            text=(
                                "lark-cli not found. Install @larksuite/cli and set LARK_CLI_PATH if needed."
                            ),
                        ),
                    ],
                )
            ct = (comment_type or "selection").strip().lower()
            if ct not in ("full", "selection", "block_id"):
                return ToolResponse(
                    content=[
                        TextBlock(
                            type="text",
                            text=f"invalid comment_type: {comment_type!r}; use full, selection, or block_id",
                        ),
                    ],
                )
            if ct == "selection" and not (selection_text or "").strip():
                return ToolResponse(
                    content=[
                        TextBlock(
                            type="text",
                            text='comment_type="selection" requires non-empty selection_text',
                        ),
                    ],
                )
            if ct == "block_id" and not (block_id or "").strip():
                return ToolResponse(
                    content=[
                        TextBlock(
                            type="text",
                            text='comment_type="block_id" requires non-empty block_id',
                        ),
                    ],
                )
            if ct == "full":
                mode: CommentMode = "full"
            elif ct == "selection":
                mode = "selection"
            else:
                mode = "block_id"
            try:
                argv = build_add_comment_argv(
                    lark_cli=lark_bin,
                    doc=doc_url.strip(),
                    comment_text=comment_text,
                    mode=mode,
                    selection_text=selection_text,
                    block_id=block_id,
                    dry_run=dry_run,
                )
            except ValueError as exc:
                return ToolResponse(
                    content=[TextBlock(type="text", text=str(exc))],
                )
            await store.append_event(
                task_id,
                "status",
                chunk=f"feishu_doc_comment: mode={ct} dry_run={dry_run}",
            )
            code, cli_log = await run_cli_streaming(store, task_id, argv)
            if cli_log:
                summary = f"exit_code={code}\n--- lark-cli +add-comment ---\n{cli_log}"
            else:
                summary = f"exit_code={code}\n(no stdout/stderr lines)"
            await store.append_event(
                task_id,
                "status",
                chunk=f"feishu_doc_comment_end: exit_code={code}",
            )
            return ToolResponse(content=[TextBlock(type="text", text=summary)])

        toolkit.register_tool_function(feishu_doc_comment)

    client_kwargs: dict[str, Any] = {}
    base = (settings.openai_base_url or "").strip()
    if base:
        client_kwargs["base_url"] = base

    model = OpenAIChatModel(
        settings.openai_model,
        api_key=api_key,
        stream=True,
        client_kwargs=client_kwargs or None,
    )

    compression_config = None
    if settings.compression_enabled:
        compression_config = ReActAgent.CompressionConfig(
            enable=True,
            agent_token_counter=OpenAITokenCounter(settings.openai_model),
            trigger_threshold=settings.compression_trigger_tokens,
            keep_recent=settings.compression_keep_recent,
        )

    sys_prompt = (
        "You are a helpful assistant. "
        "For the bundled demo CLI, use cli_exec: subcommands `slow` or `sleep --seconds 2` "
        "(pass only subcommand and args). "
        "For Feishu/Lark (飞书), use lark_cli_exec with the official lark-cli "
        "(https://github.com/larksuite/cli): pass args only, e.g. `auth status`, "
        "`calendar +agenda --format json`. Prefer `--format json` or `ndjson` for machine-readable output. "
        "Feishu doc review with highlight (划词) comments — LONG documents: "
        "(1) Call feishu_fetch_doc(doc_url) page by page. Each response ends with "
        "`--- feishu_fetch_pagination ---`: obey has_more and next_offset; repeat until has_more is false. "
        "Never claim you only saw an excerpt or ~2000 characters while has_more is still true. "
        "(2) After EACH page (or while iterating), analyze that page's markdown only; for each issue call "
        "feishu_doc_comment with comment_type=selection and selection_text copied verbatim from THAT page's "
        "markdown (unique phrase or start...end). Write comment_text yourself. "
        "(3) If one page is too large for your context, reduce `limit` on feishu_fetch_doc and use more pages. "
        "Prefer selection on docx; legacy doc may need comment_type=full. "
        "Use dry_run on feishu_doc_comment only when the user asks to preview."
    )

    async def _run_with_memory(memory: InMemoryMemory) -> None:
        agent = ReActAgent(
            name="backend_agent",
            sys_prompt=sys_prompt,
            model=model,
            formatter=OpenAIChatFormatter(),
            toolkit=toolkit,
            memory=memory,
            compression_config=compression_config,
        )

        async def agent_coroutine():
            user_msg = Msg(
                name="user",
                content=prompt,
                role="user",
            )
            return await agent(user_msg)

        async for msg, is_last_chunk in stream_printing_messages([agent], agent_coroutine()):
            text = _msg_to_text(msg)
            if text:
                await store.append_event(
                    task_id,
                    "agent",
                    chunk=text,
                    meta={"is_final_chunk": bool(is_last_chunk)},
                )

    try:
        if session_id:
            async with session_lock(session_id):
                memory = await load_session_memory(store, user_id, session_id)
                await _run_with_memory(memory)
                await store.append_event(
                    task_id,
                    "result",
                    meta={"ok": True, "mode": "agent", "session_id": session_id},
                )
                await store.update_meta(task_id, status="succeeded")
                await save_session_memory(store, user_id, session_id, memory)
        else:
            memory = InMemoryMemory()
            await _run_with_memory(memory)
            await store.append_event(task_id, "result", meta={"ok": True, "mode": "agent"})
            await store.update_meta(task_id, status="succeeded")
    except Exception as exc:
        await store.append_event(
            task_id,
            "error",
            chunk=f"{type(exc).__name__}: {exc}",
            meta={},
        )
        await store.update_meta(task_id, status="failed")
