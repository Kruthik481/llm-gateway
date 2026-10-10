import asyncio
import json
from collections import defaultdict
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx

HOSTS = {"api.cerebras.ai": "cerebras", "openrouter.ai": "openrouter"}


@dataclass
class Reply:
    text: str = "Hello there!"
    prompt_tokens: int | None = 12
    completion_tokens: int | None = 3
    finish_reason: str = "stop"
    delay_s: float = 0.0


@dataclass
class StreamReply:
    pieces: list[str] = field(default_factory=lambda: ["Hel", "lo ", "there!"])
    prompt_tokens: int = 12
    include_usage: bool = True
    delay_s: float = 0.0
    fail_after: int | None = None  # drop the connection before piece N
    error_chunk_after: int | None = None  # send an in-band error event before piece N
    keepalive_s: float = 0.0  # after the first piece, send only keep-alive comments for this long


@dataclass
class Status:
    code: int
    message: str = "upstream says no"


@dataclass
class Timeout:
    pass


@dataclass
class ConnectFail:
    pass


Behavior = Reply | StreamReply | Status | Timeout | ConnectFail


@dataclass
class Call:
    provider: str
    body: dict[str, Any]
    headers: httpx.Headers


def _completion(reply: Reply) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": "cmpl-fake",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": reply.text},
                "finish_reason": reply.finish_reason,
            }
        ],
    }
    if reply.prompt_tokens is not None and reply.completion_tokens is not None:
        body["usage"] = {
            "prompt_tokens": reply.prompt_tokens,
            "completion_tokens": reply.completion_tokens,
            "total_tokens": reply.prompt_tokens + reply.completion_tokens,
        }
    return body


async def _sse(reply: StreamReply, request: httpx.Request) -> AsyncIterator[bytes]:
    def event(payload: dict[str, Any]) -> bytes:
        return f"data: {json.dumps(payload)}\n\n".encode()

    yield event(
        {"choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}]}
    )
    for i, piece in enumerate(reply.pieces):
        if reply.fail_after == i:
            raise httpx.ReadError("connection reset by peer", request=request)
        if reply.error_chunk_after == i:
            yield event({"error": {"message": "model overloaded"}})
            return
        if reply.delay_s:
            await asyncio.sleep(reply.delay_s)
        yield event({"choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}]})
        if i == 0 and reply.keepalive_s:
            loop = asyncio.get_running_loop()
            stalled_until = loop.time() + reply.keepalive_s
            while loop.time() < stalled_until:
                await asyncio.sleep(0.05)
                yield b": keep-alive\n\n"
    yield event({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
    if reply.include_usage:
        completion = len(reply.pieces)
        yield event(
            {
                "choices": [],
                "usage": {
                    "prompt_tokens": reply.prompt_tokens,
                    "completion_tokens": completion,
                    "total_tokens": reply.prompt_tokens + completion,
                },
            }
        )
    yield b"data: [DONE]\n\n"


class FakeUpstream:
    """Scripted stand-in for Cerebras and OpenRouter, plugged in via httpx.MockTransport."""

    def __init__(self) -> None:
        self._scripts: dict[str, list[Behavior]] = defaultdict(list)
        self.calls: list[Call] = []

    def script(self, provider: str, *behaviors: Behavior) -> None:
        self._scripts[provider].extend(behaviors)

    def calls_to(self, provider: str) -> list[Call]:
        return [call for call in self.calls if call.provider == provider]

    async def handler(self, request: httpx.Request) -> httpx.Response:
        provider = HOSTS[request.url.host]
        body = json.loads(request.content)
        self.calls.append(Call(provider, body, request.headers))
        script = self._scripts[provider]
        behavior = script.pop(0) if script else (StreamReply() if body.get("stream") else Reply())
        match behavior:
            case Timeout():
                raise httpx.ReadTimeout("upstream too slow", request=request)
            case ConnectFail():
                raise httpx.ConnectError("connection refused", request=request)
            case Status(code=code, message=message):
                return httpx.Response(code, json={"error": {"message": message}})
            case Reply():
                if behavior.delay_s:
                    await asyncio.sleep(behavior.delay_s)
                return httpx.Response(200, json=_completion(behavior))
            case StreamReply():
                return httpx.Response(
                    200, headers={"content-type": "text/event-stream"}, content=_sse(behavior, request)
                )
