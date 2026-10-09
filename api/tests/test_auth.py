from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.auth import AUTH_CACHE_TTL_S, KeyResolver, parse_bearer
from app.core.errors import GatewayError
from app.core.keys import hash_key
from app.db.repo import revoke_key
from tests.helpers import new_key, new_user

Sessions = async_sessionmaker[AsyncSession]


def test_parse_bearer_accepts_gateway_keys() -> None:
    assert parse_bearer("Bearer lgw_abc") == "lgw_abc"
    assert parse_bearer("bearer lgw_abc") == "lgw_abc"


def test_parse_bearer_tolerates_whitespace() -> None:
    assert parse_bearer("  Bearer   lgw_abc  ") == "lgw_abc"


def test_parse_bearer_rejects_everything_else() -> None:
    assert parse_bearer(None) is None
    assert parse_bearer("") is None
    assert parse_bearer("Basic lgw_abc") is None
    assert parse_bearer("Bearer sk-proj-123") is None
    assert parse_bearer("lgw_abc") is None


def test_gateway_error_uses_openai_shape_and_types() -> None:
    assert GatewayError(401, "invalid_api_key", "nope").body() == {
        "error": {"message": "nope", "type": "authentication_error", "code": "invalid_api_key"}
    }
    assert GatewayError(429, "rate_limited", "slow").type == "rate_limit_error"
    assert GatewayError(502, "upstream_error", "down").type == "api_error"
    assert GatewayError(404, "model_not_found", "?").type == "invalid_request_error"


async def test_resolve_returns_none_for_unknown_keys(sessions: Sessions, redis: Redis) -> None:
    assert await KeyResolver(redis, sessions).resolve("lgw_nope") is None


async def test_resolve_caches_the_identity_for_a_minute(sessions: Sessions, redis: Redis) -> None:
    user = await new_user(sessions)
    raw, identity = await new_key(sessions, user.id)
    resolver = KeyResolver(redis, sessions)
    assert await resolver.resolve(raw) == identity
    ttl = await redis.ttl(f"key:{hash_key(raw)}")
    assert 0 < ttl <= AUTH_CACHE_TTL_S


async def test_forget_makes_a_revocation_immediate(sessions: Sessions, redis: Redis) -> None:
    user = await new_user(sessions)
    raw, identity = await new_key(sessions, user.id)
    resolver = KeyResolver(redis, sessions)
    await resolver.resolve(raw)
    async with sessions() as s, s.begin():
        key_hash = await revoke_key(s, user_id=user.id, key_id=identity.key_id)
    assert key_hash is not None
    assert await resolver.resolve(raw) == identity  # still cached
    await resolver.forget(key_hash)
    assert await resolver.resolve(raw) is None
