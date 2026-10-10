import asyncio
import json
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from fastapi.responses import StreamingResponse

from app.core.cache import CachedCompletion, replay_chunks
from app.core.providers import Finish, ProviderError, StreamEvent, TextDelta, UsageReport
from app.core.router import AllProvidersFailed, OpenedStream, UpstreamRejected
from app.core.schemas import ChatRequest
from app.proxy.service import (
    REQUEST_DEADLINE_S,
    Admission,
    deadline_failure,
    elapsed_ms,
    finalize,
    gateway_meta,
    make_record,
    record_cache_hit,
    resolved_usage,
    response_headers,
    routing_failure,
)
from app.state import GatewayState

SSE_HEADERS = {"cache-control": "no-cache", "x-accel-buffering": "no"}


def sse(payload: dict[str, Any] | str) -> bytes:
    data = (
        payload
        if isinstance(payload, str)
        else json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    )
    return f"data: {data}\n\n".encode()


class Frame:
    """Builds OpenAI `chat.completion.chunk` payloads for one response."""

    def __init__(self, adm: Admission, req: ChatRequest) -> None:
        self.id = f"chatcmpl-{adm.request_id}"
        self.created = int(time.time())
        self.model = req.model

    def _base(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "object": "chat.completion.chunk",
            "created": self.created,
            "model": self.model,
        }

    def chunk(
        self,
        delta: dict[str, Any],
        *,
        finish_reason: str | None = None,
        x_gateway: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = {**self._base(), "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}]}
        if x_gateway is not None:
            body["x_gateway"] = x_gateway
        return body

    def usage(self, prompt_tokens: int, completion_tokens: int) -> dict[str, Any]:
        return {
            **self._base(),
            "choices": [],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        }


@dataclass
class _Progress:
    parts: list[str] = field(default_factory=list)
    finish: str | None = None
    usage: UsageReport | None = None
    status: str = "partial"
    error: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    meta: dict[str, Any] = field(default_factory=dict)


def _settle(
    state: GatewayState,
    adm: Admission,
    req: ChatRequest,
    opened: OpenedStream,
    ttft_ms: int,
    progress: _Progress,
) -> None:
    target = opened.target
    text = "".join(progress.parts)
    reported = progress.usage
    prompt, completion = resolved_usage(
        req,
        text,
        reported.prompt_tokens if reported else None,
        reported.completion_tokens if reported else None,
    )
    cost = state.prices.cost(target.provider, target.model, prompt, completion)
    progress.prompt_tokens, progress.completion_tokens = prompt, completion
    progress.meta = gateway_meta(
        provider=target.provider,
        cache=adm.cache_mode,
        attempts=len(opened.attempts),
        cost=cost,
        saved=Decimal(0),
        ttft_ms=ttft_ms,
    )
    is_ok = progress.status == "ok"
    record = make_record(
        adm,
        req,
        status=progress.status,
        provider=target.provider,
        upstream_model=target.model,
        prompt_tokens=prompt,
        completion_tokens=completion,
        cost=cost,
        ttft_ms=ttft_ms,
        error_code=None if is_ok else (progress.error or "client_disconnected"),
        attempts=len(opened.attempts),
    )
    cache_value = (
        CachedCompletion(text, progress.finish or "stop", prompt, completion, target.provider, target.model)
        if is_ok and adm.cache_key is not None
        else None
    )
    finalize(
        state, adm, record, actual_tokens=prompt + completion, cache_value=cache_value, close=opened.rest
    )


async def _relay(
    state: GatewayState, adm: Admission, req: ChatRequest, opened: OpenedStream, ttft_ms: int
) -> AsyncGenerator[bytes]:
    frame = Frame(adm, req)
    progress = _Progress()
    deadline = adm.started + REQUEST_DEADLINE_S
    try:
        yield sse(frame.chunk({"role": "assistant", "content": ""}))
        event: StreamEvent | None = opened.first
        while event is not None:
            if isinstance(event, TextDelta):
                progress.parts.append(event.text)
                yield sse(frame.chunk({"content": event.text}))
            elif isinstance(event, Finish):
                progress.finish = event.reason
            else:
                progress.usage = event
            try:
                async with asyncio.timeout(deadline - time.monotonic()):
                    event = await anext(opened.rest, None)
            except TimeoutError:
                progress.error = "deadline_exceeded"
                break
        else:
            progress.status = "ok"
    except ProviderError as err:
        state.router.report_midstream_failure(opened.target.provider)
        progress.error = err.outcome
    finally:
        # Runs on success, provider failure and client disconnect alike; it only schedules work.
        _settle(state, adm, req, opened, ttft_ms, progress)
    if progress.status == "ok":
        yield sse(frame.chunk({}, finish_reason=progress.finish or "stop", x_gateway=progress.meta))
        if req.include_usage:
            yield sse(frame.usage(progress.prompt_tokens, progress.completion_tokens))
    else:
        yield sse(
            {
                "error": {
                    "message": f"The answer was cut off ({progress.error}).",
                    "type": "api_error",
                    "code": "upstream_error",
                }
            }
        )
    yield sse("[DONE]")


def _replay(
    state: GatewayState, adm: Admission, req: ChatRequest, hit: CachedCompletion
) -> StreamingResponse:
    meta = record_cache_hit(state, adm, req, hit)
    frame = Frame(adm, req)

    async def events() -> AsyncGenerator[bytes]:
        yield sse(frame.chunk({"role": "assistant", "content": ""}))
        for piece in replay_chunks(hit.text):
            yield sse(frame.chunk({"content": piece}))
        yield sse(frame.chunk({}, finish_reason=hit.finish_reason, x_gateway=meta))
        if req.include_usage:
            yield sse(frame.usage(hit.prompt_tokens, hit.completion_tokens))
        yield sse("[DONE]")

    headers = {**response_headers(adm, provider=hit.provider, cache="hit", attempts=0), **SSE_HEADERS}
    return StreamingResponse(events(), media_type="text/event-stream", headers=headers)


async def stream_response(state: GatewayState, adm: Admission, req: ChatRequest) -> StreamingResponse:
    if adm.cache_key is not None:
        hit = await state.cache.get(adm.cache_key)
        if hit is not None:
            return _replay(state, adm, req, hit)
    try:
        async with asyncio.timeout(REQUEST_DEADLINE_S):
            opened = await state.router.open_stream(adm.targets, req, fail_provider=adm.fail_provider)
    except TimeoutError as err:
        raise deadline_failure(state, adm, req) from err
    except (AllProvidersFailed, UpstreamRejected) as err:
        raise routing_failure(state, adm, req, err) from err
    ttft_ms = elapsed_ms(adm.started)
    headers = {
        **response_headers(
            adm, provider=opened.target.provider, cache=adm.cache_mode, attempts=len(opened.attempts)
        ),
        **SSE_HEADERS,
    }
    return StreamingResponse(
        _relay(state, adm, req, opened, ttft_ms), media_type="text/event-stream", headers=headers
    )
