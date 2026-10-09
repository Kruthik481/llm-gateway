import httpx

from app.main import create_app
from app.settings import Settings


async def test_healthz_reports_ok(settings: Settings) -> None:
    transport = httpx.ASGITransport(app=create_app(settings))  # no lifespan: /healthz needs no state
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
