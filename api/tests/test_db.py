from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import ApiKey, Usage, User
from app.db.session import to_async_url


def test_to_async_url_rewrites_a_neon_url() -> None:
    url = "postgresql://u:pw@ep-x-pooler.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
    assert to_async_url(url) == (
        "postgresql+asyncpg://u:pw@ep-x-pooler.ap-southeast-1.aws.neon.tech/neondb?ssl=require"
    )


def test_to_async_url_keeps_a_plain_local_url() -> None:
    assert (
        to_async_url("postgres://g:g@localhost:5434/gateway")
        == "postgresql+asyncpg://g:g@localhost:5434/gateway"
    )


async def test_round_trips_a_user_key_and_usage_row(sessions: async_sessionmaker[AsyncSession]) -> None:
    async with sessions() as s, s.begin():
        user = User(github_id=1, login="ana", avatar_url="https://a/1.png")
        s.add(user)
        await s.flush()
        key = ApiKey(user_id=user.id, name="laptop", prefix="lgw_abcdefgh", key_hash="0" * 64)
        s.add(key)
        await s.flush()
        s.add(
            Usage(
                key_id=key.id,
                user_id=user.id,
                model="gpt-oss-120b",
                provider="groq",
                upstream_model="gpt-oss-120b",
                prompt_tokens=10,
                completion_tokens=5,
                cost_usd=Decimal("0.00001450"),
                list_cost_saved_usd=Decimal(0),
                cache_hit=False,
                status="ok",
                error_code=None,
                latency_ms=120,
                ttft_ms=None,
                attempts=1,
            )
        )
    async with sessions() as s:
        row = (await s.execute(select(Usage))).scalar_one()
    assert row.cost_usd == Decimal("0.00001450")
    assert row.created_at.tzinfo is not None


async def test_usage_status_is_constrained(sessions: async_sessionmaker[AsyncSession]) -> None:
    async with sessions() as s, s.begin():
        user = User(github_id=2, login="ben", avatar_url="")
        s.add(user)
        await s.flush()
        key = ApiKey(user_id=user.id, name="k", prefix="lgw_x", key_hash="1" * 64)
        s.add(key)
        await s.flush()
    with pytest.raises(IntegrityError):
        async with sessions() as s, s.begin():
            s.add(
                Usage(
                    key_id=key.id,
                    user_id=user.id,
                    model="m",
                    provider=None,
                    upstream_model=None,
                    prompt_tokens=0,
                    completion_tokens=0,
                    cost_usd=Decimal(0),
                    list_cost_saved_usd=Decimal(0),
                    cache_hit=False,
                    status="weird",
                    error_code=None,
                    latency_ms=1,
                    ttft_ms=None,
                    attempts=0,
                )
            )
