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


@lru_cache
def get_settings() -> Settings:
    return Settings()
