import asyncio
import hmac
from collections.abc import Awaitable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST
from sqlalchemy import text

from app.core.errors import GatewayError
from app.state import GatewayState, get_state

ops_router = APIRouter(tags=["ops"])
StateDep = Annotated[GatewayState, Depends(get_state)]
CHECK_TIMEOUT_S = 2


async def _passes(check: Awaitable[Any]) -> bool:
    try:
        async with asyncio.timeout(CHECK_TIMEOUT_S):
            await check
        return True
    except Exception:
        return False


async def _postgres(state: GatewayState) -> None:
    async with state.engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


@ops_router.get("/healthz")
async def healthz() -> dict[str, bool]:
    return {"ok": True}


@ops_router.get("/readyz")
async def readyz(state: StateDep) -> JSONResponse:
    redis_ok = await _passes(state.redis.ping())
    postgres_ok = await _passes(_postgres(state))
    ok = redis_ok and postgres_ok
    return JSONResponse(
        {"ok": ok, "redis": redis_ok, "postgres": postgres_ok}, status_code=200 if ok else 503
    )


@ops_router.get("/metrics")
async def metrics(request: Request, state: StateDep) -> Response:
    scheme, _, supplied = request.headers.get("authorization", "").strip().partition(" ")
    expected = state.settings.metrics_token
    if scheme.lower() != "bearer" or not hmac.compare_digest(supplied.strip().encode(), expected.encode()):
        raise GatewayError(401, "invalid_metrics_token", "Metrics need the metrics token.")
    return Response(state.metrics.render(state.router.circuit_states()), media_type=CONTENT_TYPE_LATEST)
