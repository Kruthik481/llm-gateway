from decimal import Decimal

import pytest
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repo import KeyIdentity
from app.proxy import service
from tests.conftest import LiveGateway, StartGateway, usage_rows
from tests.fakes import Reply, Status, Timeout
from tests.helpers import chat, new_key, new_user

URL = "/v1/chat/completions"
ApiKey = tuple[str, KeyIdentity]


async def test_rejects_missing_and_unknown_keys(gateway: LiveGateway) -> None:
    for key in (None, "lgw_" + "x" * 43):
        async with gateway.client(key) as c:
            resp = await c.post(URL, json=chat())
        assert resp.status_code == 401
        assert resp.json()["error"] == {
            "message": "Invalid API key. Create one in the dashboard.",
            "type": "authentication_error",
            "code": "invalid_api_key",
        }


async def test_lists_the_model_aliases(gateway: LiveGateway, api_key: ApiKey) -> None:
    async with gateway.client(api_key[0]) as c:
        resp = await c.get("/v1/models")
    assert {m["id"] for m in resp.json()["data"]} == {"llama-3.3-70b", "qwen-3-32b"}


async def test_completes_and_records_usage(gateway: LiveGateway, api_key: ApiKey) -> None:
    raw, identity = api_key
    gateway.upstream.script("cerebras", Reply(text="4", prompt_tokens=20, completion_tokens=1))
    async with gateway.client(raw) as c:
        resp = await c.post(URL, json=chat())
    assert resp.status_code == 200
    body = resp.json()
    assert body["object"] == "chat.completion"
    assert body["model"] == "llama-3.3-70b"
    assert body["choices"][0]["message"] == {"role": "assistant", "content": "4"}
    assert body["usage"] == {"prompt_tokens": 20, "completion_tokens": 1, "total_tokens": 21}
    assert body["x_gateway"] == {
        "provider": "cerebras",
        "cache": "bypass",
        "attempts": 1,
        "cost_usd": "0.00001820",
        "saved_usd": "0",
        "ttft_ms": None,
    }
    assert resp.headers["x-gateway-provider"] == "cerebras"
    assert resp.headers["x-gateway-attempts"] == "1"
    assert resp.headers["x-ratelimit-remaining-requests"] == "19"
    [row] = await usage_rows(gateway)
    assert (row.status, row.provider, row.prompt_tokens, row.completion_tokens) == ("ok", "cerebras", 20, 1)
    assert row.cost_usd == Decimal("0.00001820")
    assert await gateway.state.budget.used_today(str(identity.user_id)) == 21


async def test_unknown_model_is_a_404(gateway: LiveGateway, api_key: ApiKey) -> None:
    async with gateway.client(api_key[0]) as c:
        resp = await c.post(URL, json=chat(model="gpt-9"))
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "model_not_found"


async def test_validation_errors_are_openai_shaped_400s(gateway: LiveGateway, api_key: ApiKey) -> None:
    async with gateway.client(api_key[0]) as c:
        resp = await c.post(URL, json=chat(max_tokens=5000))
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_request"
    assert "max_tokens" in resp.json()["error"]["message"]


async def test_oversized_prompt_is_rejected_before_budget(gateway: LiveGateway, api_key: ApiKey) -> None:
    raw, identity = api_key
    async with gateway.client(raw) as c:
        resp = await c.post(URL, json=chat(messages=[{"role": "user", "content": "x" * 1_000_000}]))
    assert resp.status_code == 400
    assert "too long" in resp.json()["error"]["message"]
    assert await gateway.state.budget.used_today(str(identity.user_id)) == 0
    assert gateway.upstream.calls == []


async def test_falls_back_and_says_so(gateway: LiveGateway, api_key: ApiKey) -> None:
    gateway.upstream.script("cerebras", Status(429))
    async with gateway.client(api_key[0]) as c:
        resp = await c.post(URL, json=chat())
    assert resp.status_code == 200
    assert resp.headers["x-gateway-provider"] == "openrouter"
    assert resp.headers["x-gateway-attempts"] == "2"
    [row] = await usage_rows(gateway)
    assert (row.provider, row.attempts) == ("openrouter", 2)


async def test_all_providers_failing_is_a_502_with_a_full_refund(
    gateway: LiveGateway, api_key: ApiKey
) -> None:
    raw, identity = api_key
    gateway.upstream.script("cerebras", Timeout())
    gateway.upstream.script("openrouter", Status(503))
    async with gateway.client(raw) as c:
        resp = await c.post(URL, json=chat())
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "upstream_error"
    assert "cerebras:timeout, openrouter:503" in resp.json()["error"]["message"]
    [row] = await usage_rows(gateway)
    assert (row.status, row.error_code, row.attempts) == ("error", "upstream_error", 2)
    assert await gateway.state.budget.used_today(str(identity.user_id)) == 0


async def test_upstream_400_passes_through_without_fallback(gateway: LiveGateway, api_key: ApiKey) -> None:
    gateway.upstream.script("cerebras", Status(400, "prompt is malformed"))
    async with gateway.client(api_key[0]) as c:
        resp = await c.post(URL, json=chat())
    assert resp.status_code == 400
    assert "prompt is malformed" in resp.json()["error"]["message"]
    assert gateway.upstream.calls_to("openrouter") == []


async def test_deadline_becomes_a_504(
    gateway: LiveGateway, api_key: ApiKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw, identity = api_key
    monkeypatch.setattr(service, "REQUEST_DEADLINE_S", 0.2)
    gateway.upstream.script("cerebras", Reply(delay_s=2))
    async with gateway.client(raw) as c:
        resp = await c.post(URL, json=chat())
    assert resp.status_code == 504
    assert resp.json()["error"]["code"] == "timeout"
    await usage_rows(gateway)
    assert await gateway.state.budget.used_today(str(identity.user_id)) == 0


async def test_temperature_zero_answers_are_cached_per_user(
    gateway: LiveGateway, api_key: ApiKey, sessions: async_sessionmaker[AsyncSession]
) -> None:
    raw, identity = api_key
    async with gateway.client(raw) as c:
        first = await c.post(URL, json=chat(temperature=0))
        await gateway.state.tasks.drain()  # the cache write happens after the response
        second = await c.post(URL, json=chat(temperature=0))
    assert (first.headers["x-gateway-cache"], second.headers["x-gateway-cache"]) == ("miss", "hit")
    assert second.json()["choices"] == first.json()["choices"]
    assert len(gateway.upstream.calls) == 1
    meta = second.json()["x_gateway"]
    assert meta["cost_usd"] == "0"
    assert Decimal(meta["saved_usd"]) > 0
    rows = await usage_rows(gateway)
    assert [r.cache_hit for r in rows] == [False, True]
    used = await gateway.state.budget.used_today(str(identity.user_id))
    assert used == rows[0].prompt_tokens + rows[0].completion_tokens

    ben = await new_user(sessions, github_id=2, login="ben")
    ben_key, _ = await new_key(sessions, ben.id)
    async with gateway.client(ben_key) as c:
        third = await c.post(URL, json=chat(temperature=0))
    assert third.headers["x-gateway-cache"] == "miss"


async def test_cache_can_be_bypassed(gateway: LiveGateway, api_key: ApiKey) -> None:
    async with gateway.client(api_key[0], **{"x-gateway-cache": "bypass"}) as c:
        await c.post(URL, json=chat(temperature=0))
        await gateway.state.tasks.drain()
        resp = await c.post(URL, json=chat(temperature=0))
    assert resp.headers["x-gateway-cache"] == "bypass"
    assert len(gateway.upstream.calls) == 2


async def test_rate_limit_is_a_429_with_retry_after(start_gateway: StartGateway, api_key: ApiKey) -> None:
    gateway = await start_gateway(rate_limit_per_minute=2)
    async with gateway.client(api_key[0]) as c:
        statuses = [(await c.post(URL, json=chat())).status_code for _ in range(2)]
        blocked = await c.post(URL, json=chat())
    assert statuses == [200, 200]
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"
    assert blocked.headers["retry-after"] == "30"


async def test_daily_budget_is_a_429(start_gateway: StartGateway, api_key: ApiKey) -> None:
    gateway = await start_gateway(user_daily_tokens=50)
    async with gateway.client(api_key[0]) as c:
        resp = await c.post(URL, json=chat(max_tokens=64))
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "budget_exceeded"


async def test_simulated_outage_uses_the_fallback(gateway: LiveGateway, api_key: ApiKey) -> None:
    async with gateway.client(api_key[0], **{"x-gateway-debug-fail": "cerebras"}) as c:
        resp = await c.post(URL, json=chat())
    assert resp.headers["x-gateway-provider"] == "openrouter"
    assert gateway.upstream.calls_to("cerebras") == []


async def test_the_openai_sdk_works_unchanged(gateway: LiveGateway, api_key: ApiKey) -> None:
    client = AsyncOpenAI(base_url=f"{gateway.url}/v1", api_key=api_key[0], max_retries=0)
    resp = await client.chat.completions.create(
        model="llama-3.3-70b", messages=[{"role": "user", "content": "hi"}]
    )
    assert resp.choices[0].message.content == "Hello there!"
    assert {m.id async for m in client.models.list()} == {"llama-3.3-70b", "qwen-3-32b"}


async def test_redis_outage_fails_closed(start_gateway: StartGateway, api_key: ApiKey) -> None:
    gateway = await start_gateway(redis_url="redis://localhost:6399/0")
    async with gateway.client(api_key[0]) as c:
        resp = await c.post(URL, json=chat())
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "service_unavailable"


async def test_cors_allows_only_the_dashboard_origin(gateway: LiveGateway) -> None:
    preflight = {
        "access-control-request-method": "POST",
        "access-control-request-headers": "authorization,content-type,x-gateway-debug-fail",
    }
    async with gateway.client() as c:
        ok = await c.options(URL, headers={"origin": "http://localhost:3000", **preflight})
        bad = await c.options(URL, headers={"origin": "https://evil.example", **preflight})
    assert ok.status_code == 200
    assert ok.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert bad.status_code == 400
