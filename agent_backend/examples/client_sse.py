"""
调用 agent-backend：提交任务 + SSE 流式拉取事件。

依赖: pip install httpx（项目已依赖）

用法（在仓库根目录）::

  python -m agent_backend.examples.client_sse
  python -m agent_backend.examples.client_sse --base-url http://127.0.0.1:8080 --prompt "hello" --mode mock

多轮对话（同一 session_id 多次提交任务）::

  # 第一轮：自动生成 session_id（stderr 会打印，请记下）
  python -m agent_backend.examples.client_sse --new-session --mode agent --prompt "你好"

  # 第二轮起：使用同一 session_id
  python -m agent_backend.examples.client_sse --session-id <上一步打印的 UUID> --mode agent --prompt "接着上面说"
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from typing import Any, Iterator

import httpx


def submit_task(
    base_url: str,
    prompt: str,
    *,
    mode: str | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
    timeout: float = 30.0,
) -> str:
    base = base_url.rstrip("/")
    url = f"{base}/api/v1/tasks"
    body: dict[str, Any] = {"prompt": prompt}
    if mode is not None:
        body["mode"] = mode
    if user_id:
        body["user_id"] = user_id
    if session_id:
        body["session_id"] = session_id
    with httpx.Client(timeout=timeout) as client:
        r = client.post(url, json=body)
        r.raise_for_status()
        data = r.json()
    task_id = data.get("task_id")
    if not task_id:
        raise RuntimeError(f"unexpected response: {data}")
    return task_id


def iter_sse_events(
    base_url: str,
    task_id: str,
    *,
    from_seq: int = 0,
) -> Iterator[dict[str, Any]]:
    """
    连接 ``GET /api/v1/tasks/{task_id}/events?from_seq=...`` ，逐条产出 JSON 事件。

    每条事件形如: ``{"seq", "type", "chunk", "meta"}``。
    """
    base = base_url.rstrip("/")
    url = f"{base}/api/v1/tasks/{task_id}/events"
    params = {"from_seq": from_seq}
    # 长任务：连接后读流不设上限；仅限制连接建立时间
    stream_timeout = httpx.Timeout(connect=60.0, read=None, write=60.0, pool=60.0)
    with httpx.Client(timeout=stream_timeout) as client:
        with client.stream("GET", url, params=params) as response:
            response.raise_for_status()
            buf = ""
            for chunk in response.iter_text():
                buf += chunk
                while "\n\n" in buf:
                    block, buf = buf.split("\n\n", 1)
                    for line in block.splitlines():
                        line = line.strip()
                        if not line or line.startswith(":"):
                            continue
                        if line.lower().startswith("data:"):
                            payload = line[5:].strip()
                            if payload == "[DONE]":
                                return
                            yield json.loads(payload)


def _session_id_label(session_id: str | None) -> str:
    return session_id if session_id else "(未设置)"


def run_flow(
    base_url: str,
    prompt: str,
    mode: str | None,
    from_seq: int,
    session_id: str | None = None,
) -> None:
    print(f"session_id={_session_id_label(session_id)}", file=sys.stderr)
    task_id = submit_task(base_url, prompt, mode=mode, session_id=session_id)
    print(f"task_id={task_id}", file=sys.stderr)

    for ev in iter_sse_events(base_url, task_id, from_seq=from_seq):
        et = ev.get("type")
        chunk = ev.get("chunk") or ""
        seq = ev.get("seq")
        if chunk:
            print(f"[{seq}] {et}: {chunk}")
        else:
            print(f"[{seq}] {et} {ev.get('meta', {})}")
        if et == "result":
            print(f"session_id={_session_id_label(session_id)}", file=sys.stderr)
            break
        if et == "error":
            break


def main() -> None:
    p = argparse.ArgumentParser(description="Submit task and stream SSE events")
    p.add_argument("--base-url", default="http://127.0.0.1:8080", help="API 根地址")
    p.add_argument("--prompt", default="hello", help="任务提示")
    p.add_argument(
        "--mode",
        default="agent",
        choices=("mock", "agent"),
        help="mock 无需 LLM；agent 需服务端配置 OPENAI_*",
    )
    p.add_argument(
        "--from-seq",
        type=int,
        default=0,
        help="断线重连时从上次的 seq 之后拉取",
    )
    p.add_argument(
        "--session-id",
        default=None,
        metavar="ID",
        help="多轮对话：与上一轮相同的字符串（可自造 UUID，或用 --new-session 自动生成）",
    )
    p.add_argument(
        "--new-session",
        action="store_true",
        help="为本轮随机生成 session_id 并提交；请根据 stderr 打印的 session_id 在后续命令中传入 --session-id",
    )
    args = p.parse_args()
    if args.new_session and args.session_id:
        print("错误：不能同时使用 --new-session 与 --session-id", file=sys.stderr)
        raise SystemExit(2)
    session_id = str(uuid.uuid4()) if args.new_session else args.session_id
    run_flow(
        args.base_url,
        args.prompt,
        args.mode,
        args.from_seq,
        session_id=session_id,
    )


if __name__ == "__main__":
    main()
