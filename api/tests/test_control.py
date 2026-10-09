import time
from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx
import jwt
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import utcnow
from app.db.repo import KeyIdentity
from app.settings import Settings
from tests.conftest import LiveGateway
from tests.helpers import chat, usage_row

Sessions = async_sessionmaker[AsyncSession]


def token(
    settings: Settings, *, github_id: Any = 7, login: str = "ana", ttl: int = 300, secret: str | None = None
) -> str:
    now = int(time.time())
    claims = {
        "github_id": github_id,
        "login": login,
        "avatar_url": "https://a/7.png",
        "iat": now,
        "exp": now + ttl,
    }
    return jwt.encode(claims, secret or settings.control_jwt_secret, algorithm="HS256")


def control(gateway: LiveGateway, settings: Settings, **kwargs: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=gateway.url, headers={"authorization": f"Bearer {token(settings, **kwargs)}"}, timeout=15
    )


async def make_key(
    gateway: LiveGateway, settings: Settings, name: str = "laptop", **kwargs: Any
) -> dict[str, Any]:
    async with control(gateway, settings, **kwargs) as c:
        resp = await c.post("/control/keys", json={"name": name})
    assert resp.status_code == 201, resp.text
    body: dict[str, Any] = resp.json()
    return body


@pytest.mark.parametrize(
    "kwargs",
    [{"secret": "x" * 40}, {"ttl": -60}, {"ttl": 3600}, {"github_id": "7"}],
)
async def test_bad_tokens_are_401(gateway: LiveGateway, settings: Settings, kwargs: dict[str, Any]) -> None:
    async with control(gateway, settings, **kwargs) as c:
        resp = await c.get("/control/me")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "invalid_token"


async def test_missing_token_is_401(gateway: LiveGateway) -> None:
    async with gateway.client() as c:
        assert (await c.get("/control/me")).status_code == 401


async def test_me_upserts_the_user(gateway: LiveGateway, settings: Settings) -> None:
    async with control(gateway, settings) as c:
        first = (await c.get("/control/me")).json()
    async with control(gateway, settings, login="ana-renamed") as c:
        second = (await c.get("/control/me")).json()
    assert first["id"] == second["id"]
    assert (first["github_id"], second["login"]) == (7, "ana-renamed")


async def test_key_lifecycle_and_immediate_revocation(gateway: LiveGateway, settings: Settings) -> None:
    created = await make_key(gateway, settings)
    assert created["key"].startswith("lgw_")
    assert created["prefix"] == created["key"][:12]
    async with gateway.client(created["key"]) as c:
        assert (await c.post("/v1/chat/completions", json=chat())).status_code == 200  # caches the key
    await gateway.state.tasks.drain()
    async with control(gateway, settings) as c:
        listed = (await c.get("/control/keys")).json()
        assert [k["name"] for k in listed] == ["laptop"]
        assert "key" not in listed[0]
        assert listed[0]["requests_24h"] == 1
        assert (await c.delete(f"/control/keys/{created['id']}")).status_code == 204
        assert (await c.get("/control/keys")).json() == []
    async with gateway.client(created["key"]) as c:
        assert (await c.post("/v1/chat/completions", json=chat())).status_code == 401


async def test_fourth_key_is_a_409(gateway: LiveGateway, settings: Settings) -> None:
    for i in range(3):
        await make_key(gateway, settings, name=f"k{i}")
    async with control(gateway, settings) as c:
        resp = await c.post("/control/keys", json={"name": "k4"})
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "key_limit"


@pytest.mark.parametrize("name", ["", "   ", "x" * 41])
async def test_key_names_are_validated(gateway: LiveGateway, settings: Settings, name: str) -> None:
    async with control(gateway, settings) as c:
        resp = await c.post("/control/keys", json={"name": name})
    assert resp.status_code == 400


async def test_cannot_revoke_someone_elses_key(gateway: LiveGateway, settings: Settings) -> None:
    created = await make_key(gateway, settings)
    async with control(gateway, settings, github_id=8, login="ben") as c:
        resp = await c.delete(f"/control/keys/{created['id']}")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "key_not_found"


async def test_usage_summary_fills_days_and_aggregates(
    gateway: LiveGateway, settings: Settings, sessions: Sessions
) -> None:
    created = await make_key(gateway, settings)
    async with control(gateway, settings) as c:
        me = (await c.get("/control/me")).json()
    identity = KeyIdentity(key_id=UUID(created["id"]), user_id=UUID(me["id"]), prefix=created["prefix"])
    async with sessions() as s, s.begin():
        s.add(usage_row(identity, latency_ms=100, ttft_ms=40))
        s.add(
            usage_row(
                identity,
                provider="openrouter",
                attempts=2,
                latency_ms=300,
                model="qwen-3-32b",
                cost_usd=Decimal("0.00000100"),
            )
        )
        s.add(
            usage_row(
                identity, cache_hit=True, cost_usd=Decimal(0), list_cost_saved_usd=Decimal("0.00002000")
            )
        )
        s.add(usage_row(identity, created_at=utcnow() - timedelta(days=2)))
        s.add(usage_row(identity, created_at=utcnow() - timedelta(days=20)))
    async with control(gateway, settings) as c:
        summary = (await c.get("/control/usage/summary", params={"days": 7})).json()
    assert len(summary["days"]) == 7
    assert summary["days"][-1]["requests"] == 3
    assert summary["days"][-3]["requests"] == 1
    assert sum(d["requests"] for d in summary["days"]) == 4
    assert summary["fallbacks"] == 1
    assert Decimal(summary["cache_saved_usd"]) == Decimal("0.00002000")
    assert {p["provider"]: p["requests"] for p in summary["providers"]} == {"cerebras": 2, "openrouter": 1}
    assert {m["model"] for m in summary["cost_by_model"]} == {"llama-3.3-70b", "qwen-3-32b"}
    assert summary["latency_ms"]["p50"] == 100
    assert summary["ttft_ms"]["p50"] == 40
    assert summary["budget"] == {"used": 0, "limit": 50_000}


async def test_usage_summary_rejects_bad_ranges(gateway: LiveGateway, settings: Settings) -> None:
    async with control(gateway, settings) as c:
        assert (await c.get("/control/usage/summary", params={"days": 0})).status_code == 400
        assert (await c.get("/control/usage/summary", params={"days": 31})).status_code == 400


async def test_recent_usage_is_metadata_only_and_per_user(gateway: LiveGateway, settings: Settings) -> None:
    created = await make_key(gateway, settings)
    async with gateway.client(created["key"]) as c:
        await c.post("/v1/chat/completions", json=chat())
    await gateway.state.tasks.drain()
    async with control(gateway, settings) as c:
        mine = (await c.get("/control/usage/recent")).json()
    async with control(gateway, settings, github_id=8, login="ben") as c:
        theirs = (await c.get("/control/usage/recent")).json()
    assert len(mine) == 1
    assert mine[0]["key_prefix"] == created["prefix"]
    assert set(mine[0]) == {
        "created_at",
        "key_prefix",
        "model",
        "provider",
        "prompt_tokens",
        "completion_tokens",
        "cost_usd",
        "cache_hit",
        "status",
        "latency_ms",
        "ttft_ms",
        "attempts",
    }
    assert theirs == []


async def test_public_stats_need_no_auth_and_are_cached(gateway: LiveGateway, settings: Settings) -> None:
    created = await make_key(gateway, settings)
    async with gateway.client() as c:
        before = (await c.get("/control/stats/public")).json()
    async with gateway.client(created["key"]) as c:
        await c.post("/v1/chat/completions", json=chat())
    await gateway.state.tasks.drain()
    async with gateway.client() as c:
        cached = (await c.get("/control/stats/public")).json()
    assert before == cached == {"requests_today": 0, "cache_hit_rate": 0.0, "fallbacks_today": 0}
    await gateway.state.redis.delete("stats:public")
    async with gateway.client() as c:
        fresh = (await c.get("/control/stats/public")).json()
    assert fresh["requests_today"] == 1
