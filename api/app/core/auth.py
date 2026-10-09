import json
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.keys import KEY_PREFIX, hash_key
from app.db.repo import KeyIdentity, find_key_by_hash

AUTH_CACHE_TTL_S = 60


def parse_bearer(header: str | None) -> str | None:
    if not header:
        return None
    scheme, _, token = header.strip().partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token.startswith(KEY_PREFIX):
        return None
    return token


def _dump(identity: KeyIdentity) -> str:
    return json.dumps(
        {"key_id": str(identity.key_id), "user_id": str(identity.user_id), "prefix": identity.prefix}
    )


def _load(raw: str | bytes) -> KeyIdentity:
    data = json.loads(raw)
    return KeyIdentity(key_id=UUID(data["key_id"]), user_id=UUID(data["user_id"]), prefix=data["prefix"])


class KeyResolver:
    """Maps a raw API key to its identity: Redis first (60s), then Postgres."""

    def __init__(self, redis: Redis, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._redis = redis
        self._sessions = sessions

    async def resolve(self, raw_key: str) -> KeyIdentity | None:
        key_hash = hash_key(raw_key)
        cached = await self._redis.get(f"key:{key_hash}")
        if cached is not None:
            return _load(cached)
        async with self._sessions() as session:
            identity = await find_key_by_hash(session, key_hash)
        if identity is not None:
            await self._redis.set(f"key:{key_hash}", _dump(identity), ex=AUTH_CACHE_TTL_S)
        return identity

    async def forget(self, key_hash: str) -> None:
        await self._redis.delete(f"key:{key_hash}")
