import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
import uvicorn
from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.models import Usage
from app.db.repo import KeyIdentity
from app.db.session import make_engine, make_sessionmaker
from app.main import create_app
from app.settings import Settings
from app.state import GatewayState
from tests.fakes import FakeUpstream
from tests.helpers import new_key, new_user

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
        groq_api_key="csk-test",
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


@dataclass
class LiveGateway:
    url: str
    app: FastAPI
    upstream: FakeUpstream

    @property
    def state(self) -> GatewayState:
        state: GatewayState = self.app.state.gw
        return state

    def client(self, key: str | None = None, **headers: str) -> httpx.AsyncClient:
        merged = {**({"authorization": f"Bearer {key}"} if key else {}), **headers}
        return httpx.AsyncClient(base_url=self.url, headers=merged, timeout=15)


StartGateway = Callable[..., Awaitable[LiveGateway]]


@pytest.fixture
def upstream() -> FakeUpstream:
    return FakeUpstream()


@pytest.fixture
async def start_gateway(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    redis: Redis,
    upstream: FakeUpstream,
) -> AsyncIterator[StartGateway]:
    running: list[tuple[uvicorn.Server, asyncio.Task[None]]] = []

    async def start(**overrides: object) -> LiveGateway:
        app = create_app(
            settings.model_copy(update=overrides), upstream_transport=httpx.MockTransport(upstream.handler)
        )
        server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", lifespan="on")
        )
        task = asyncio.create_task(server.serve())
        while not server.started:
            if task.done():
                task.result()
            await asyncio.sleep(0.01)
        port = server.servers[0].sockets[0].getsockname()[1]
        running.append((server, task))
        return LiveGateway(url=f"http://127.0.0.1:{port}", app=app, upstream=upstream)

    yield start
    for server, task in running:
        server.should_exit = True
        await task


@pytest.fixture
async def gateway(start_gateway: StartGateway) -> LiveGateway:
    return await start_gateway()


@pytest.fixture
async def api_key(sessions: async_sessionmaker[AsyncSession]) -> tuple[str, KeyIdentity]:
    user = await new_user(sessions)
    return await new_key(sessions, user.id)


async def usage_rows(gateway: LiveGateway) -> list[Usage]:
    await gateway.state.tasks.drain()
    async with gateway.state.sessions() as session:
        return list((await session.execute(select(Usage).order_by(Usage.id))).scalars())
