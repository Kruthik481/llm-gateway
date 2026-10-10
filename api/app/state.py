from dataclasses import dataclass
from pathlib import Path

import httpx
from fastapi import Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.auth import KeyResolver
from app.core.breaker import CircuitBreaker
from app.core.budget import Budget
from app.core.cache import ResponseCache
from app.core.catalog import PROVIDERS, Catalog
from app.core.ledger import Ledger
from app.core.metrics import Metrics
from app.core.pricing import PriceBook
from app.core.providers import PROVIDER_TIMEOUT, OpenAICompatProvider, Provider
from app.core.ratelimit import RateLimiter
from app.core.router import Router
from app.core.tasks import TaskTracker
from app.db.session import make_engine, make_sessionmaker
from app.settings import Settings

CONFIG_DIR = Path(__file__).resolve().parents[1]
REDIS_TIMEOUT_S = 2


@dataclass
class GatewayState:
    settings: Settings
    redis: Redis
    engine: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]
    http: httpx.AsyncClient
    resolver: KeyResolver
    limiter: RateLimiter
    budget: Budget
    cache: ResponseCache
    catalog: Catalog
    prices: PriceBook
    router: Router
    ledger: Ledger
    tasks: TaskTracker
    metrics: Metrics

    async def aclose(self) -> None:
        await self.tasks.drain()
        await self.http.aclose()
        await self.redis.aclose()
        await self.engine.dispose()


def build_providers(settings: Settings, http: httpx.AsyncClient) -> dict[str, Provider]:
    return {
        "groq": OpenAICompatProvider("groq", settings.groq_base_url, settings.groq_api_key, http),
        "openrouter": OpenAICompatProvider(
            "openrouter",
            settings.openrouter_base_url,
            settings.openrouter_api_key,
            http,
            extra_headers={"HTTP-Referer": settings.web_origin, "X-Title": "LLM Gateway"},
        ),
    }


def build_state(
    settings: Settings, upstream_transport: httpx.AsyncBaseTransport | None = None
) -> GatewayState:
    redis = Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_timeout=REDIS_TIMEOUT_S,
        socket_connect_timeout=REDIS_TIMEOUT_S,
    )
    engine = make_engine(settings.database_url)
    sessions = make_sessionmaker(engine)
    http = httpx.AsyncClient(timeout=PROVIDER_TIMEOUT, transport=upstream_transport)
    providers = build_providers(settings, http)
    return GatewayState(
        settings=settings,
        redis=redis,
        engine=engine,
        sessions=sessions,
        http=http,
        resolver=KeyResolver(redis, sessions),
        limiter=RateLimiter(redis, settings.rate_limit_per_minute),
        budget=Budget(
            redis, user_limit=settings.user_daily_tokens, global_limit=settings.global_daily_tokens
        ),
        cache=ResponseCache(redis),
        catalog=Catalog.from_yaml(CONFIG_DIR / "models.yaml", PROVIDERS),
        prices=PriceBook.from_yaml(CONFIG_DIR / "pricing.yaml"),
        router=Router(providers, {name: CircuitBreaker() for name in providers}),
        ledger=Ledger(sessions),
        tasks=TaskTracker(),
        metrics=Metrics(),
    )


def get_state(request: Request) -> GatewayState:
    state: GatewayState = request.app.state.gw
    return state
