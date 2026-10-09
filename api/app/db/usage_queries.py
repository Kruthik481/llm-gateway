from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class DayStat:
    day: date
    requests: int
    tokens: int


@dataclass(frozen=True)
class ModelCost:
    model: str
    cost_usd: Decimal


@dataclass(frozen=True)
class ProviderCount:
    provider: str
    requests: int


@dataclass(frozen=True)
class Percentiles:
    p50: float | None
    p95: float | None


@dataclass(frozen=True)
class UsageSummary:
    days: list[DayStat]
    cost_by_model: list[ModelCost]
    cache_saved_usd: Decimal
    providers: list[ProviderCount]
    fallbacks: int
    latency_ms: Percentiles
    ttft_ms: Percentiles


@dataclass(frozen=True)
class RecentRow:
    created_at: datetime
    key_prefix: str
    model: str
    provider: str | None
    prompt_tokens: int
    completion_tokens: int
    cost_usd: Decimal
    cache_hit: bool
    status: str
    latency_ms: int
    ttft_ms: int | None
    attempts: int


@dataclass(frozen=True)
class PublicStats:
    requests_today: int
    cache_hit_rate: float
    fallbacks_today: int


def day_start(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=UTC)


_DAILY = text(
    """
    SELECT (d AT TIME ZONE 'UTC')::date AS day,
           count(u.id) AS requests,
           coalesce(sum(u.prompt_tokens + u.completion_tokens), 0) AS tokens
    FROM generate_series(CAST(:first AS timestamptz), CAST(:last AS timestamptz), interval '1 day') AS d
    LEFT JOIN usage u
      ON u.user_id = :user_id AND u.created_at >= d AND u.created_at < d + interval '1 day'
    GROUP BY d
    ORDER BY d
    """
)
_COST_BY_MODEL = text(
    """
    SELECT model, sum(cost_usd) AS cost FROM usage
    WHERE user_id = :user_id AND created_at >= :first
    GROUP BY model ORDER BY cost DESC, model
    """
)
_TOTALS = text(
    """
    SELECT coalesce(sum(list_cost_saved_usd), 0) AS saved,
           count(*) FILTER (WHERE attempts > 1 AND status <> 'error') AS fallbacks,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms) AS latency_p50,
           percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) AS latency_p95,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY ttft_ms) AS ttft_p50,
           percentile_cont(0.95) WITHIN GROUP (ORDER BY ttft_ms) AS ttft_p95
    FROM usage WHERE user_id = :user_id AND created_at >= :first
    """
)
_PROVIDERS = text(
    """
    SELECT provider, count(*) AS requests FROM usage
    WHERE user_id = :user_id AND created_at >= :first AND provider IS NOT NULL AND NOT cache_hit
    GROUP BY provider ORDER BY requests DESC, provider
    """
)
_RECENT = text(
    """
    SELECT u.created_at, k.prefix, u.model, u.provider, u.prompt_tokens, u.completion_tokens, u.cost_usd,
           u.cache_hit, u.status, u.latency_ms, u.ttft_ms, u.attempts
    FROM usage u JOIN api_keys k ON k.id = u.key_id
    WHERE u.user_id = :user_id
    ORDER BY u.created_at DESC, u.id DESC
    LIMIT :limit
    """
)
_PUBLIC = text(
    """
    SELECT count(*) AS requests,
           count(*) FILTER (WHERE cache_hit) AS hits,
           count(*) FILTER (WHERE attempts > 1 AND status <> 'error') AS fallbacks
    FROM usage WHERE created_at >= :first
    """
)


async def usage_summary(session: AsyncSession, user_id: UUID, *, days: int, today: date) -> UsageSummary:
    params = {"user_id": user_id, "first": day_start(today - timedelta(days=days - 1))}
    daily = await session.execute(_DAILY, {**params, "last": day_start(today)})
    costs = await session.execute(_COST_BY_MODEL, params)
    totals = (await session.execute(_TOTALS, params)).one()
    providers = await session.execute(_PROVIDERS, params)
    return UsageSummary(
        days=[DayStat(row.day, row.requests, row.tokens) for row in daily],
        cost_by_model=[ModelCost(row.model, row.cost) for row in costs],
        cache_saved_usd=totals.saved,
        providers=[ProviderCount(row.provider, row.requests) for row in providers],
        fallbacks=totals.fallbacks,
        latency_ms=Percentiles(totals.latency_p50, totals.latency_p95),
        ttft_ms=Percentiles(totals.ttft_p50, totals.ttft_p95),
    )


async def recent_usage(session: AsyncSession, user_id: UUID, *, limit: int) -> list[RecentRow]:
    rows = await session.execute(_RECENT, {"user_id": user_id, "limit": limit})
    return [RecentRow(*row) for row in rows]


async def public_stats(session: AsyncSession, *, today: date) -> PublicStats:
    row = (await session.execute(_PUBLIC, {"first": day_start(today)})).one()
    rate = round(row.hits / row.requests, 3) if row.requests else 0.0
    return PublicStats(requests_today=row.requests, cache_hit_rate=rate, fallbacks_today=row.fallbacks)
