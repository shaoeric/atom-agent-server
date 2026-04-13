"""Verify AgentScope Runtime `AgentApp` and streaming task flags import (CI / manual)."""

from __future__ import annotations


def verify_imports() -> None:
    from agentscope_runtime.engine import AgentApp  # noqa: F401

    _ = AgentApp(
        app_name="spike",
        enable_stream_task=False,
    )


if __name__ == "__main__":
    verify_imports()
    print("agentscope-runtime AgentApp import OK")
