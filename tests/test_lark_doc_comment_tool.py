"""Unit tests for lark doc comment argv builder."""

from agent_backend.lark_doc_comment_tool import build_add_comment_argv


def test_build_full_comment_argv() -> None:
    argv = build_add_comment_argv(
        lark_cli="lark-cli",
        doc="https://x.com/docx/abc",
        comment_text="hello",
        mode="full",
    )
    assert argv[0] == "lark-cli"
    assert argv[1:4] == ["drive", "+add-comment", "--doc"]
    assert "--doc" in argv
    assert argv[argv.index("--doc") + 1] == "https://x.com/docx/abc"
    assert "--content" in argv
    assert "--full-comment" in argv
    assert '"text": "hello"' in argv[argv.index("--content") + 1]


def test_build_selection_argv() -> None:
    argv = build_add_comment_argv(
        lark_cli="lark-cli",
        doc="doxcnxxx",
        comment_text="note",
        mode="selection",
        selection_text="流程...步骤",
    )
    assert "--selection-with-ellipsis" in argv
    i = argv.index("--selection-with-ellipsis")
    assert argv[i + 1] == "流程...步骤"


def test_build_dry_run() -> None:
    argv = build_add_comment_argv(
        lark_cli="lark-cli",
        doc="u",
        comment_text="x",
        mode="full",
        dry_run=True,
    )
    assert argv[-1] == "--dry-run"
