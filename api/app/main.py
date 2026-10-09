from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.http_errors import register_error_handlers
from app.proxy.routes import router as proxy_router
from app.settings import Settings
from app.state import build_state

ALLOWED_REQUEST_HEADERS = ["authorization", "content-type", "x-gateway-cache", "x-gateway-debug-fail"]
EXPOSED_HEADERS = [
    "x-request-id",
    "x-gateway-provider",
    "x-gateway-cache",
    "x-gateway-attempts",
    "x-ratelimit-limit-requests",
    "x-ratelimit-remaining-requests",
    "x-ratelimit-reset-requests",
    "retry-after",
]


def create_app(
    settings: Settings | None = None, *, upstream_transport: httpx.AsyncBaseTransport | None = None
) -> FastAPI:
    resolved = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        state = build_state(resolved, upstream_transport)
        app.state.gw = state
        try:
            yield
        finally:
            await state.aclose()

    app = FastAPI(title="LLM Gateway", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[resolved.web_origin],
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=ALLOWED_REQUEST_HEADERS,
        expose_headers=EXPOSED_HEADERS,
    )
    register_error_handlers(app)
    app.include_router(proxy_router)

    @app.get("/healthz")
    async def healthz() -> dict[str, bool]:
        return {"ok": True}

    return app
