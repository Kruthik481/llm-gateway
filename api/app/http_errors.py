import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.core.errors import GatewayError

log = structlog.get_logger()


def _json(error: GatewayError) -> JSONResponse:
    return JSONResponse(error.body(), status_code=error.status, headers=error.headers)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(GatewayError)
    async def gateway_error(request: Request, exc: GatewayError) -> JSONResponse:
        return _json(exc)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = exc.errors()
        first = errors[0] if errors else {"loc": (), "msg": "Invalid request"}
        location = ".".join(str(part) for part in first.get("loc", ()) if part != "body")
        message = f"{location}: {first['msg']}" if location else str(first["msg"])
        return _json(GatewayError(400, "invalid_request", message))

    @app.exception_handler(RedisConnectionError)
    @app.exception_handler(RedisTimeoutError)
    async def redis_unavailable(request: Request, exc: Exception) -> JSONResponse:
        log.error("redis_unavailable", error=str(exc), path=request.url.path)
        return _json(
            GatewayError(
                503,
                "service_unavailable",
                "The gateway cannot reach its rate-limit store, so it is refusing requests rather than "
                "running unmetered. Try again shortly.",
            )
        )

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.error(
            "unhandled_error",
            exc_info=exc,
            path=request.url.path,
            request_id=getattr(request.state, "request_id", None),
        )
        return _json(
            GatewayError(500, "internal_error", "Internal error. Quote the x-request-id if you report it.")
        )
