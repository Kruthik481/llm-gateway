from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.keys import generate_key, hash_key, key_prefix
from app.db.models import ApiKey, Usage, User, utcnow

MAX_ACTIVE_KEYS = 3


class KeyLimitReached(Exception):
    pass


@dataclass(frozen=True)
class KeyIdentity:
    key_id: UUID
    user_id: UUID
    prefix: str


@dataclass(frozen=True)
class KeyRow:
    id: UUID
    name: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None
    requests_24h: int


async def upsert_user(session: AsyncSession, *, github_id: int, login: str, avatar_url: str) -> User:
    stmt = (
        pg_insert(User)
        .values(github_id=github_id, login=login, avatar_url=avatar_url)
        .on_conflict_do_update(
            index_elements=[User.github_id], set_={"login": login, "avatar_url": avatar_url}
        )
        .returning(User)
        .execution_options(populate_existing=True)
    )
    return (await session.scalars(stmt)).one()


async def create_key(session: AsyncSession, *, user_id: UUID, name: str) -> tuple[ApiKey, str]:
    # Lock the user row so two concurrent creates cannot both see 2 active keys.
    await session.execute(select(User.id).where(User.id == user_id).with_for_update())
    active = await session.scalar(
        select(func.count()).select_from(ApiKey).where(ApiKey.user_id == user_id, ApiKey.revoked_at.is_(None))
    )
    if (active or 0) >= MAX_ACTIVE_KEYS:
        raise KeyLimitReached
    raw = generate_key()
    key = ApiKey(user_id=user_id, name=name, prefix=key_prefix(raw), key_hash=hash_key(raw))
    session.add(key)
    await session.flush()
    return key, raw


async def list_keys(session: AsyncSession, user_id: UUID) -> list[KeyRow]:
    since = utcnow() - timedelta(hours=24)
    stmt = (
        select(
            ApiKey.id,
            ApiKey.name,
            ApiKey.prefix,
            ApiKey.created_at,
            func.max(Usage.created_at),
            func.count(Usage.id).filter(Usage.created_at >= since),
        )
        .outerjoin(Usage, Usage.key_id == ApiKey.id)
        .where(ApiKey.user_id == user_id, ApiKey.revoked_at.is_(None))
        .group_by(ApiKey.id)
        .order_by(ApiKey.created_at)
    )
    return [KeyRow(*row) for row in (await session.execute(stmt)).all()]


async def revoke_key(session: AsyncSession, *, user_id: UUID, key_id: UUID) -> str | None:
    stmt = (
        update(ApiKey)
        .where(ApiKey.id == key_id, ApiKey.user_id == user_id, ApiKey.revoked_at.is_(None))
        .values(revoked_at=utcnow())
        .returning(ApiKey.key_hash)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def find_key_by_hash(session: AsyncSession, key_hash: str) -> KeyIdentity | None:
    stmt = select(ApiKey.id, ApiKey.user_id, ApiKey.prefix).where(
        ApiKey.key_hash == key_hash, ApiKey.revoked_at.is_(None)
    )
    row = (await session.execute(stmt)).one_or_none()
    return KeyIdentity(key_id=row[0], user_id=row[1], prefix=row[2]) if row else None
