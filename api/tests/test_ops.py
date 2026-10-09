import pytest
from structlog.testing import capture_logs

from app.db.repo import KeyIdentity
from app.settings import Settings
from tests.conftest import LiveGateway, StartGateway, usage_rows
from tests.helpers import chat

ApiKey = tuple[str, KeyIdentity]


async def test_request_ids_are_generated_and_echoed(gateway: LiveGateway) -> None:
    async with gateway.client() as c:
        generated = await c.get("/healthz")
        echoed = await c.get("/healthz", headers={"x-request-id": "trace-123"})
        replaced = await c.get("/healthz", headers={"x-request-id": "bad id with spaces"})
    assert len(generated.headers["x-request-id"]) == 32
    assert echoed.headers["x-request-id"] == "trace-123"
    assert replaced.headers["x-request-id"] != "bad id with spaces"


async def test_proxy_responses_carry_the_middleware_request_id(gateway: LiveGateway, api_key: ApiKey) -> None:
    async with gateway.client(api_key[0], **{"x-request-id": "abc-1"}) as c:
        resp = await c.post("/v1/chat/completions", json=chat())
    assert resp.headers["x-request-id"] == "abc-1"
    assert resp.json()["id"] == "chatcmpl-abc-1"


async def test_each_request_logs_one_line_without_prompt_text(gateway: LiveGateway, api_key: ApiKey) -> None:
    with capture_logs() as logs:
        async with gateway.client(api_key[0]) as c:
            await c.post("/v1/chat/completions", json=chat())
        await usage_rows(gateway)
    [line] = [entry for entry in logs if entry["event"] == "request"]
    assert line["provider"] == "cerebras"
    assert line["key"] == api_key[1].prefix
    assert line["status"] == "ok"
    assert "What is 2+2?" not in str(line)


async def test_metrics_need_the_token(gateway: LiveGateway, settings: Settings, api_key: ApiKey) -> None:
    async with gateway.client(api_key[0]) as c:
        await c.post("/v1/chat/completions", json=chat())
    await usage_rows(gateway)
    async with gateway.client() as c:
        denied = await c.get("/metrics")
        allowed = await c.get("/metrics", headers={"authorization": f"Bearer {settings.metrics_token}"})
    assert denied.status_code == 401
    assert allowed.status_code == 200
    assert 'gateway_requests_total{cache="miss",provider="cerebras",status="ok"} 1.0' in allowed.text
    assert 'gateway_circuit_open{provider="cerebras"} 0.0' in allowed.text


async def test_readyz_reports_dependencies(gateway: LiveGateway, start_gateway: StartGateway) -> None:
    async with gateway.client() as c:
        ok = await c.get("/readyz")
    assert ok.json() == {"ok": True, "redis": True, "postgres": True}
    broken = await start_gateway(redis_url="redis://localhost:6399/0")
    async with broken.client() as c:
        down = await c.get("/readyz")
    assert down.status_code == 503
    assert down.json() == {"ok": False, "redis": False, "postgres": True}


@pytest.mark.parametrize("path", ["/healthz", "/readyz"])
async def test_ops_endpoints_need_no_key(gateway: LiveGateway, path: str) -> None:
    async with gateway.client() as c:
        assert (await c.get(path)).status_code == 200
