"""
向 agent-backend 提交任务并拉取结果。

用法::

  python -m agent_backend.examples.client --prompt "你好"
  python -m agent_backend.examples.client --prompt "第二句" --session-id <UUID>
  python -m agent_backend.examples.client --prompt "x" --no-stream

``--no-stream`` 时：仅打印每条 agent 消息的完成态（``meta.is_final_chunk``），避免流式中间块重复；
``--stream`` 时：仍逐块打印。

依赖: httpx（项目已依赖）
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from agent_backend.examples.client_sse import iter_sse_events, submit_task


def _print_event(ev: dict[str, Any]) -> None:
    et = ev.get("type")
    chunk = ev.get("chunk") or ""
    seq = ev.get("seq")
    if chunk:
        print(f"[{seq}] {et}: {chunk}")
    else:
        print(f"[{seq}] {et} {ev.get('meta', {})}")


def _should_emit_event(ev: dict[str, Any], *, only_final_agent_chunks: bool) -> bool:
    """非流式模式下仅输出 agent 每条消息的「最后一块」，避免同一段 text 流式重复打印。"""
    if not only_final_agent_chunks:
        return True
    if ev.get("type") != "agent":
        return True
    meta = ev.get("meta") or {}
    return bool(meta.get("is_final_chunk", True))


def run(
    *,
    base_url: str,
    prompt: str,
    session_id: str | None,
    mode: str | None,
    stream: bool,
    from_seq: int,
) -> int:
    sid_label = session_id if session_id else "(未设置)"
    print(f"session_id={sid_label}", file=sys.stderr)
    task_id = submit_task(base_url, prompt, mode=mode, session_id=session_id)
    print(f"task_id={task_id}", file=sys.stderr)

    if stream:
        for ev in iter_sse_events(base_url, task_id, from_seq=from_seq):
            _print_event(ev)
            et = ev.get("type")
            if et == "result":
                print(f"session_id={sid_label}", file=sys.stderr)
                return 0
            if et == "error":
                return 1
        return 1

    # 非流式：收齐 SSE 再输出；agent 仅打印每段内容的最终块（多轮则多段 think/text）
    events: list[dict[str, Any]] = []
    for ev in iter_sse_events(base_url, task_id, from_seq=from_seq):
        events.append(ev)
        if ev.get("type") in ("result", "error"):
            break
    for ev in events:
        if _should_emit_event(ev, only_final_agent_chunks=True):
            _print_event(ev)
    print(f"session_id={sid_label}", file=sys.stderr)
    if events and events[-1].get("type") == "error":
        return 1
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description="调用 agent-backend：prompt / session-id / stream")
    p.add_argument("--base-url", default="http://127.0.0.1:8080", help="API 根地址")
    p.add_argument("--prompt", required=True, help="任务提示词")
    p.add_argument(
        "--session-id",
        default=None,
        metavar="ID",
        help="多轮对话会话 ID；不传则为单次任务上下文",
    )
    p.add_argument(
        "--stream",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="开启：SSE 边收边打印；关闭：结束后一次性打印全部事件",
    )
    p.add_argument(
        "--mode",
        default=None,
        choices=("mock", "agent"),
        help="不传则使用服务端默认（MOCK_AGENT_DEFAULT）",
    )
    p.add_argument(
        "--from-seq",
        type=int,
        default=0,
        help="断线重连时从该 seq 之后拉取",
    )
    args = p.parse_args()
    session_id = args.session_id.strip() if args.session_id else None
    if session_id == "":
        session_id = None

    code = run(
        base_url=args.base_url,
        prompt=args.prompt,
        session_id=session_id,
        mode=args.mode,
        stream=args.stream,
        from_seq=args.from_seq,
    )
    raise SystemExit(code)


if __name__ == "__main__":
    main()
