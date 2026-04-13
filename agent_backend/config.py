from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    redis_url: str = "redis://127.0.0.1:6379/0"
    max_concurrent_tasks: int = 50
    mock_agent_default: bool = False
    task_stream_key: str = "agent:tasks:pending"
    consumer_group: str = "workers"
    consumer_name: str = "worker-1"
    dashscope_api_key: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
