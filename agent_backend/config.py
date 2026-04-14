from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    #: ``memory``: asyncio queue + dicts in process (default). ``redis``: Streams + consumer group.
    store_backend: Literal["memory", "redis"] = "memory"
    #: When ``store_backend=memory``, start worker loop inside API process (required to share queue).
    embed_worker: bool = True

    redis_url: str = "redis://127.0.0.1:6379/0"
    max_concurrent_tasks: int = 50
    mock_agent_default: bool = True
    task_stream_key: str = "agent:tasks:pending"
    consumer_group: str = "workers"
    consumer_name: str = "worker-1"

    #: OpenAI-compatible Chat Completions (via ``openai.AsyncClient``).
    openai_api_key: str | None = None
    #: Custom API base URL (e.g. vLLM, Azure OpenAI proxy). Empty = SDK default.
    openai_base_url: str = ""
    openai_model: str = "gpt-4o-mini"

    #: 为 ReActAgent 注册飞书官方 CLI（``lark-cli``）工具；需本机已安装 ``@larksuite/cli``。
    enable_lark_cli_tool: bool = True
    #: 可执行文件路径；留空则从 ``PATH`` 解析 ``lark-cli``（Windows 下通常为 ``.cmd``）。
    lark_cli_path: str = ""
    #: ``feishu_fetch_doc`` 工具返回给模型的合并输出最大字符数（避免长文档被过早截断）。
    lark_doc_fetch_max_tool_chars: int = 200_000
    #: ``feishu_fetch_doc`` 默认 ``limit``（分页块数/页大小，与 lark-cli 一致）；可调大减少分页次数。
    lark_doc_fetch_default_limit: int = 10_000

    #: ReActAgent 内置记忆压缩（超阈值时结构化摘要）；会额外调用 LLM。
    compression_enabled: bool = True
    compression_trigger_tokens: int = 80_000
    compression_keep_recent: int = 5

    #: 仅 ``STORE_BACKEND=redis`` 时：会话 JSON 的过期秒数；``None`` 表示不过期。
    session_ttl_seconds: int | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
