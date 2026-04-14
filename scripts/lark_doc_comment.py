#!/usr/bin/env python3
"""
使用 lark-cli 对飞书云文档添加「全文评论」或「划词（局部）评论」。

依赖：已安装并在 PATH 中的 `lark-cli`，且已完成飞书授权（见 lark-shared）。

划词评论仅支持新版文档 docx（及解析为 docx 的知识库链接）；旧版 doc 仅支持全文评论。
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence

# 允许直接 `python scripts/lark_doc_comment.py` 从仓库根目录运行
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agent_backend.lark_doc_comment_tool import (  # noqa: E402
    CommentMode,
    build_add_comment_argv,
)


def _run(argv: list[str]) -> int:
    print("执行:", " ".join(argv[:6]) + " ... [content] ...", file=sys.stderr)
    try:
        subprocess.run(argv, check=True)
    except subprocess.CalledProcessError as e:
        return e.returncode
    except FileNotFoundError:
        print(
            f"未找到命令: {argv[0]!r}。请安装 lark-cli 并加入 PATH。",
            file=sys.stderr,
        )
        return 127
    return 0


def interactive(lark_cli: str) -> int:
    print("飞书文档评论（lark-cli drive +add-comment）\n")
    doc = input("文档链接或 token（支持 docx/doc/wiki URL）: ").strip()
    if not doc:
        print("未输入文档链接。", file=sys.stderr)
        return 2

    print("\n模式：1 = 划词评论（局部）  2 = 全文评论（文档级评审）")
    mode = input("请选择 [1/2] (默认 1): ").strip() or "1"

    comment_mode: CommentMode = "selection"
    selection_text = ""
    block_id = ""

    if mode == "2":
        comment_mode = "full"
    else:
        print(
            "\n划词定位：输入文档中要批注的片段。\n"
            "  - 可输入连续几个字（需唯一匹配）\n"
            "  - 或用「开头...结尾」缩小范围（与 lark-cli --selection-with-ellipsis 一致）\n"
        )
        sel = input("定位文本: ").strip()
        if not sel:
            print("划词模式需要非空定位文本。", file=sys.stderr)
            return 2
        use_block = input("是否改用 block_id（已知块 ID）[y/N]: ").strip().lower()
        if use_block in ("y", "yes"):
            comment_mode = "block_id"
            block_id = sel
        else:
            selection_text = sel

    comment = input("\n评论内容: ").strip()
    if not comment:
        print("评论内容不能为空。", file=sys.stderr)
        return 2

    dry = input("\n仅预览（--dry-run，不实际发送）[y/N]: ").strip().lower()
    dry_run = dry in ("y", "yes")

    try:
        argv = build_add_comment_argv(
            lark_cli=lark_cli,
            doc=doc,
            comment_text=comment,
            mode=comment_mode,
            selection_text=selection_text,
            block_id=block_id,
            dry_run=dry_run,
        )
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    return _run(argv)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="通过 lark-cli 为飞书文档添加划词或全文评论。",
    )
    parser.add_argument(
        "--lark-cli",
        default=shutil.which("lark-cli") or "lark-cli",
        help="lark-cli 可执行文件路径（默认从 PATH 查找）",
    )
    parser.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="交互式输入链接、模式与评论内容",
    )
    parser.add_argument(
        "--doc",
        help="文档 URL 或 token（docx / doc / wiki）",
    )
    parser.add_argument(
        "--comment",
        "-m",
        help="评论正文（纯文本，会转为 reply_elements）",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--selection",
        "-s",
        metavar="TEXT",
        help="划词定位串，传给 --selection-with-ellipsis（与 lark-cli 一致）",
    )
    group.add_argument(
        "--block-id",
        "-b",
        metavar="ID",
        help="已知块 ID 时直接划词评论（与 --selection 二选一）",
    )
    parser.add_argument(
        "--full-comment",
        action="store_true",
        help="全文评论（文档级），不划词",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅预览请求，不写入",
    )

    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.interactive:
        return interactive(args.lark_cli)

    if not args.doc and not args.comment and sys.stdin.isatty():
        return interactive(args.lark_cli)

    if not args.doc or not args.comment:
        parser.error("非交互模式需要同时指定 --doc 与 --comment（或使用 -i）")

    if args.full_comment and (args.selection or args.block_id):
        parser.error("--full-comment 不能与 --selection / --block-id 同时使用")

    if not args.full_comment and not args.selection and not args.block_id:
        parser.error(
            "请指定划词方式：--selection 或 --block-id，或使用 --full-comment 做全文评论"
        )

    if args.full_comment:
        mode: CommentMode = "full"
    elif args.block_id:
        mode = "block_id"
    else:
        mode = "selection"

    try:
        argv = build_add_comment_argv(
            lark_cli=args.lark_cli,
            doc=args.doc,
            comment_text=args.comment,
            mode=mode,
            selection_text=args.selection or "",
            block_id=args.block_id or "",
            dry_run=args.dry_run,
        )
    except ValueError as e:
        parser.error(str(e))

    return _run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
