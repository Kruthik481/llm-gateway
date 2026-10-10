from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Usage, User
from app.db.repo import KeyIdentity, create_key, upsert_user


async def new_user(
    sessions: async_sessionmaker[AsyncSession], github_id: int = 1, login: str = "ana"
) -> User:
    async with sessions() as s, s.begin():
        return await upsert_user(s, github_id=github_id, login=login, avatar_url=f"https://a/{github_id}.png")


async def new_key(
    sessions: async_sessionmaker[AsyncSession], user_id: UUID, name: str = "test"
) -> tuple[str, KeyIdentity]:
    async with sessions() as s, s.begin():
        key, raw = await create_key(s, user_id=user_id, name=name)
    return raw, KeyIdentity(key_id=key.id, user_id=user_id, prefix=key.prefix)


def usage_row(identity: KeyIdentity, **overrides: Any) -> Usage:
    values: dict[str, Any] = {
        "key_id": identity.key_id,
        "user_id": identity.user_id,
        "model": "gpt-oss-120b",
        "provider": "groq",
        "upstream_model": "gpt-oss-120b",
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "cost_usd": Decimal("0.00001450"),
        "list_cost_saved_usd": Decimal(0),
        "cache_hit": False,
        "status": "ok",
        "error_code": None,
        "latency_ms": 100,
        "ttft_ms": None,
        "attempts": 1,
    }
    values.update(overrides)
    return Usage(**values)


def chat(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": "gpt-oss-120b",
        "messages": [{"role": "user", "content": "What is 2+2?"}],
        "temperature": 0.7,
        "max_tokens": 64,
    }
    body.update(overrides)
    return body
