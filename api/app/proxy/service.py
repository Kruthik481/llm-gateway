import asyncio
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

import structlog
from fastapi.responses import JSONResponse
from starlette.datastructures import Headers

from app.core.budget import (
    BudgetExceeded,
    Reservation,
    estimate_completion_tokens,
    estimate_prompt_tokens,
    estimate_tokens,
)
from app.core.cache import CachedCompletion, cache_key, is_cacheable
from app.core.catalog import Target
from app.core.errors import GatewayError
from app.core.ledger import UsageRecord
from app.core.providers import StreamEvent
from app.core.ratelimit import RateDecision, rate_headers
from app.core.router import AllProvidersFailed, Attempt, UpstreamRejected
from app.core.schemas import ChatRequest
from app.db.repo import KeyIdentity
from app.state import GatewayState

log = structlog.get_logger()

REQUEST_DEADLINE_S = 60.0
CacheMode = Literal["hit", "miss", "bypass"]


@dataclass(frozen=True)
class Admission:
    identity: KeyIdentity
    request_id: str
    targets: tuple[Target, ...]
    rate: RateDecision
    reservation: Reservation
    cache_key: str | None
    fail_provider: str | None
    started: float

    @property
    def cache_mode(self) -> CacheMode:
        return "miss" if self.cache_key is not None else "bypass"


def elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


async def admit(
    state: GatewayState, identity: KeyIdentity, req: ChatRequest, headers: Headers, request_id: str
) -> Admission:
    started = time.monotonic()
    targets = state.catalog.targets(req.model)
    if targets is None:
        raise GatewayError(
            404, "model_not_found", f"Unknown model '{req.model}'. GET /v1/models lists the available ones."
        )
    rate = await state.limiter.hit(str(identity.key_id))
    if not rate.allowed:
        raise GatewayError(
            429,
            "rate_limited",
            f"Rate limit of {rate.limit} requests per minute reached for this key.",
            headers={**rate_headers(rate), "retry-after": str(rate.retry_after_s)},
        )
    try:
        reservation = await state.budget.reserve(
            str(identity.user_id), estimate_tokens(req.prompt_chars(), req.max_tokens)
        )
    except BudgetExceeded as exc:
        if exc.scope == "user":
            raise GatewayError(
                429,
                "budget_exceeded",
                "Daily token budget used up. It resets at 00:00 UTC.",
                headers=rate_headers(rate),
            ) from exc
        raise GatewayError(
            429,
            "global_cap_reached",
            "The demo's daily token cap is reached. It resets at 00:00 UTC.",
            headers=rate_headers(rate),
        ) from exc
    bypass = headers.get("x-gateway-cache", "").strip().lower() == "bypass"
    return Admission(
        identity=identity,
        request_id=request_id,
        targets=targets,
        rate=rate,
        reservation=reservation,
        cache_key=cache_key(str(identity.user_id), req) if is_cacheable(req, bypass=bypass) else None,
        fail_provider=headers.get("x-gateway-debug-fail", "").strip().lower() or None,
        started=started,
    )


def response_headers(adm: Admission, *, provider: str, cache: CacheMode, attempts: int) -> dict[str, str]:
    return {
        "x-request-id": adm.request_id,
        "x-gateway-provider": provider,
        "x-gateway-cache": cache,
        "x-gateway-attempts": str(attempts),
        **rate_headers(adm.rate),
    }


def gateway_meta(
    *, provider: str, cache: CacheMode, attempts: int, cost: Decimal, saved: Decimal, ttft_ms: int | None
) -> dict[str, Any]:
    return {
        "provider": provider,
        "cache": cache,
        "attempts": attempts,
        "cost_usd": f"{cost:f}",
        "saved_usd": f"{saved:f}",
        "ttft_ms": ttft_ms,
    }


def resolved_usage(
    req: ChatRequest, text: str, prompt_tokens: int | None, completion_tokens: int | None
) -> tuple[int, int]:
    """Provider-reported usage, or estimates when the provider sent none."""
    prompt = prompt_tokens if prompt_tokens is not None else estimate_prompt_tokens(req.prompt_chars())
    completion = completion_tokens if completion_tokens is not None else estimate_completion_tokens(text)
    return prompt, completion


def make_record(
    adm: Admission,
    req: ChatRequest,
    *,
    status: str,
    attempts: int,
    provider: str | None = None,
    upstream_model: str | None = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    cost: Decimal = Decimal(0),
    saved: Decimal = Decimal(0),
    cache_hit: bool = False,
    error_code: str | None = None,
    ttft_ms: int | None = None,
) -> UsageRecord:
    return UsageRecord(
        key_id=adm.identity.key_id,
        user_id=adm.identity.user_id,
        model=req.model,
        provider=provider,
        upstream_model=upstream_model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=cost,
        list_cost_saved_usd=saved,
        cache_hit=cache_hit,
        status=status,
        error_code=error_code,
        latency_ms=elapsed_ms(adm.started),
        ttft_ms=ttft_ms,
        attempts=attempts,
    )


def finalize(
    state: GatewayState,
    adm: Admission,
    record: UsageRecord,
    *,
    actual_tokens: int,
    cache_value: CachedCompletion | None = None,
    close: AsyncGenerator[StreamEvent] | None = None,
) -> None:
    """Settle the budget, store a cacheable answer and write the ledger row, off the request path."""

    async def run() -> None:
        if close is not None:
            await close.aclose()
        try:
            await state.budget.settle(adm.reservation, actual_tokens)
        except Exception:
            log.exception("budget_settle_failed", request_id=adm.request_id)
        if cache_value is not None and adm.cache_key is not None:
            try:
                await state.cache.put(adm.cache_key, cache_value)
            except Exception:
                log.exception("cache_put_failed", request_id=adm.request_id)
        await state.ledger.write(record)

    state.tasks.spawn(run())


def _describe(attempts: list[Attempt]) -> str:
    return ", ".join(f"{a.provider}:{a.outcome}" for a in attempts)


def routing_failure(
    state: GatewayState, adm: Admission, req: ChatRequest, err: AllProvidersFailed | UpstreamRejected
) -> GatewayError:
    if isinstance(err, UpstreamRejected):
        record = make_record(
            adm,
            req,
            status="error",
            error_code="invalid_request",
            provider=err.provider,
            attempts=len(err.attempts),
        )
        finalize(state, adm, record, actual_tokens=0)
        return GatewayError(400, "invalid_request", f"{err.provider} rejected the request: {err.detail}")
    record = make_record(adm, req, status="error", error_code="upstream_error", attempts=len(err.attempts))
    finalize(state, adm, record, actual_tokens=0)
    return GatewayError(502, "upstream_error", f"All providers failed: {_describe(err.attempts)}")


def deadline_failure(state: GatewayState, adm: Admission, req: ChatRequest) -> GatewayError:
    finalize(
        state, adm, make_record(adm, req, status="error", error_code="timeout", attempts=0), actual_tokens=0
    )
    return GatewayError(504, "timeout", f"The providers did not answer within {REQUEST_DEADLINE_S:.0f}s.")


def record_cache_hit(
    state: GatewayState, adm: Admission, req: ChatRequest, hit: CachedCompletion
) -> dict[str, Any]:
    saved = state.prices.cost(hit.provider, hit.upstream_model, hit.prompt_tokens, hit.completion_tokens)
    record = make_record(
        adm,
        req,
        status="ok",
        provider=hit.provider,
        upstream_model=hit.upstream_model,
        prompt_tokens=hit.prompt_tokens,
        completion_tokens=hit.completion_tokens,
        saved=saved,
        cache_hit=True,
        attempts=0,
    )
    finalize(state, adm, record, actual_tokens=0)
    return gateway_meta(
        provider=hit.provider, cache="hit", attempts=0, cost=Decimal(0), saved=saved, ttft_ms=None
    )


def completion_body(
    adm: Admission,
    req: ChatRequest,
    *,
    text: str,
    finish_reason: str,
    prompt_tokens: int,
    completion_tokens: int,
    meta: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": f"chatcmpl-{adm.request_id}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": req.model,
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": finish_reason}
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
        "x_gateway": meta,
    }


async def complete_response(state: GatewayState, adm: Admission, req: ChatRequest) -> JSONResponse:
    if adm.cache_key is not None:
        hit = await state.cache.get(adm.cache_key)
        if hit is not None:
            meta = record_cache_hit(state, adm, req, hit)
            body = completion_body(
                adm,
                req,
                text=hit.text,
                finish_reason=hit.finish_reason,
                prompt_tokens=hit.prompt_tokens,
                completion_tokens=hit.completion_tokens,
                meta=meta,
            )
            return JSONResponse(
                body, headers=response_headers(adm, provider=hit.provider, cache="hit", attempts=0)
            )
    try:
        async with asyncio.timeout(REQUEST_DEADLINE_S):
            target, completion, attempts = await state.router.complete(
                adm.targets, req, fail_provider=adm.fail_provider
            )
    except TimeoutError as err:
        raise deadline_failure(state, adm, req) from err
    except (AllProvidersFailed, UpstreamRejected) as err:
        raise routing_failure(state, adm, req, err) from err

    prompt, completion_tokens = resolved_usage(
        req, completion.text, completion.prompt_tokens, completion.completion_tokens
    )
    cost = state.prices.cost(target.provider, target.model, prompt, completion_tokens)
    finish_reason = completion.finish_reason or "stop"
    record = make_record(
        adm,
        req,
        status="ok",
        provider=target.provider,
        upstream_model=target.model,
        prompt_tokens=prompt,
        completion_tokens=completion_tokens,
        cost=cost,
        attempts=len(attempts),
    )
    cache_value = (
        CachedCompletion(
            completion.text, finish_reason, prompt, completion_tokens, target.provider, target.model
        )
        if adm.cache_key is not None
        else None
    )
    finalize(state, adm, record, actual_tokens=prompt + completion_tokens, cache_value=cache_value)
    meta = gateway_meta(
        provider=target.provider,
        cache=adm.cache_mode,
        attempts=len(attempts),
        cost=cost,
        saved=Decimal(0),
        ttft_ms=None,
    )
    body = completion_body(
        adm,
        req,
        text=completion.text,
        finish_reason=finish_reason,
        prompt_tokens=prompt,
        completion_tokens=completion_tokens,
        meta=meta,
    )
    return JSONResponse(
        body,
        headers=response_headers(adm, provider=target.provider, cache=adm.cache_mode, attempts=len(attempts)),
    )
