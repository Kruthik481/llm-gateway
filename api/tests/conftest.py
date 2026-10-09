import os

import pytest

from app.settings import Settings

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://gateway:gateway@localhost:5434/gateway_test"
)
TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6380/15")


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url=TEST_DATABASE_URL,
        redis_url=TEST_REDIS_URL,
        cerebras_api_key="csk-test",
        openrouter_api_key="sk-or-test",
        control_jwt_secret="test-control-secret-0123456789abcdef",
        metrics_token="test-metrics-token",
        web_origin="http://localhost:3000",
    )
