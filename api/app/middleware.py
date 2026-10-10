import re
from uuid import uuid4

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import GatewayError

MAX_BODY_BYTES = 256 * 1024

_VALID_ID = re.compile(r"^[A-Za-z0-9-]{1,64}$")


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = Headers(scope=scope).get("x-request-id", "")
        request_id = incoming if _VALID_ID.match(incoming) else uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                if "x-request-id" not in headers:
                    headers.append("x-request-id", request_id)
            await send(message)

        await self.app(scope, receive, send_with_id)


class BodyLimitMiddleware:
    """Buffers the request body up to MAX_BODY_BYTES and rejects anything larger before it is parsed."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] != "http.request":
                return  # the client disconnected before sending its body
            body += message.get("body", b"")
            if len(body) > MAX_BODY_BYTES:
                error = GatewayError(
                    413, "request_too_large", f"Request bodies are limited to {MAX_BODY_BYTES // 1024} KB."
                )
                await JSONResponse(error.body(), status_code=413)(scope, receive, send)
                return
            if not message.get("more_body", False):
                break
        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if replayed:
                return await receive()  # later calls watch for a client disconnect
            replayed = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, replay, send)
