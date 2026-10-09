import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.session import make_engine, make_sessionmaker
from app.settings import Settings

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://gateway:gateway@localhost:5434/gateway_test"
)
TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6380/15")
API_DIR = Path(__file__).resolve().parents[1]


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


@pytest.fixture(scope="session")
async def engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    eng = make_engine(settings.database_url)
    async with eng.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    # Alembic's env.py calls asyncio.run(), so it must run outside this event loop.
    env = {**os.environ, "DATABASE_URL": settings.database_url}
    await asyncio.to_thread(
        subprocess.run, [sys.executable, "-m", "alembic", "upgrade", "head"], cwd=API_DIR, env=env, check=True
    )
    yield eng
    await eng.dispose()


@pytest.fixture
async def sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE usage, api_keys, users RESTART IDENTITY CASCADE"))
    return make_sessionmaker(engine)


@pytest.fixture
async def redis(settings: Settings) -> AsyncIterator[Redis]:
    client = Redis.from_url(settings.redis_url, decode_responses=True)
    await client.flushdb()
    yield client
    await client.aclose()
