import os

import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "redis: needs running Redis at REDIS_URL",
    )


@pytest.fixture
def redis_url() -> str:
    return os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/15")
