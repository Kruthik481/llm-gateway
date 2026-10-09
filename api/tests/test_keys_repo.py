import asyncio
import hashlib
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.keys import generate_key, hash_key, key_prefix
from app.db.models import ApiKey, utcnow
from app.db.repo import KeyLimitReached, create_key, find_key_by_hash, list_keys, revoke_key, upsert_user
from tests.helpers import new_key, new_user, usage_row

Sessions = async_sessionmaker[AsyncSession]


def test_generated_keys_have_prefix_entropy_and_sha256() -> None:
    key = generate_key()
    assert key.startswith("lgw_")
    assert len(key) == 47  # "lgw_" + 43 chars of base64url(32 bytes)
    assert key_prefix(key) == key[:12]
    assert hash_key(key) == hashlib.sha256(key.encode()).hexdigest()
    assert generate_key() != key


async def test_upsert_user_creates_then_updates(sessions: Sessions) -> None:
    first = await new_user(sessions, github_id=9, login="old")
    async with sessions() as s, s.begin():
        second = await upsert_user(s, github_id=9, login="new", avatar_url="https://a/new.png")
    assert second.id == first.id
    assert second.login == "new"


async def test_create_key_stores_only_the_hash(sessions: Sessions) -> None:
    user = await new_user(sessions)
    raw, identity = await new_key(sessions, user.id, name="laptop")
    async with sessions() as s:
        stored = (await s.execute(select(ApiKey))).scalar_one()
    assert stored.key_hash == hash_key(raw)
    assert stored.prefix == raw[:12]
    assert raw not in (stored.key_hash, stored.prefix, stored.name)
    assert identity.prefix == stored.prefix


async def test_fourth_active_key_is_refused_until_one_is_revoked(sessions: Sessions) -> None:
    user = await new_user(sessions)
    identities = [(await new_key(sessions, user.id, name=f"k{i}"))[1] for i in range(3)]
    with pytest.raises(KeyLimitReached):
        await new_key(sessions, user.id, name="k4")
    async with sessions() as s, s.begin():
        assert await revoke_key(s, user_id=user.id, key_id=identities[0].key_id) is not None
    await new_key(sessions, user.id, name="k4")


async def test_concurrent_creates_respect_the_limit(sessions: Sessions) -> None:
    user = await new_user(sessions)
    await new_key(sessions, user.id, name="a")
    await new_key(sessions, user.id, name="b")

    async def attempt(i: int) -> bool:
        try:
            async with sessions() as s, s.begin():
                await create_key(s, user_id=user.id, name=f"race{i}")
            return True
        except KeyLimitReached:
            return False

    results = await asyncio.gather(*(attempt(i) for i in range(5)))
    assert results.count(True) == 1


async def test_find_key_by_hash_ignores_revoked_keys(sessions: Sessions) -> None:
    user = await new_user(sessions)
    raw, identity = await new_key(sessions, user.id)
    async with sessions() as s:
        assert await find_key_by_hash(s, hash_key(raw)) == identity
    async with sessions() as s, s.begin():
        await revoke_key(s, user_id=user.id, key_id=identity.key_id)
    async with sessions() as s:
        assert await find_key_by_hash(s, hash_key(raw)) is None


async def test_revoke_only_touches_your_own_active_key(sessions: Sessions) -> None:
    ana = await new_user(sessions, github_id=1, login="ana")
    ben = await new_user(sessions, github_id=2, login="ben")
    _, ana_key = await new_key(sessions, ana.id)
    async with sessions() as s, s.begin():
        assert await revoke_key(s, user_id=ben.id, key_id=ana_key.key_id) is None
        assert await revoke_key(s, user_id=ana.id, key_id=ana_key.key_id) is not None
        assert await revoke_key(s, user_id=ana.id, key_id=ana_key.key_id) is None


async def test_list_keys_reports_last_use_and_requests_in_24h(sessions: Sessions) -> None:
    user = await new_user(sessions)
    _, used = await new_key(sessions, user.id, name="used")
    await new_key(sessions, user.id, name="idle")
    async with sessions() as s, s.begin():
        s.add(usage_row(used))
        s.add(usage_row(used))
        s.add(usage_row(used, created_at=utcnow() - timedelta(days=2)))
    async with sessions() as s:
        rows = {row.name: row for row in await list_keys(s, user.id)}
    assert rows["used"].requests_24h == 2
    assert rows["used"].last_used_at is not None
    assert rows["idle"].requests_24h == 0
    assert rows["idle"].last_used_at is None
