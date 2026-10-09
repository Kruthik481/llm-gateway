from collections.abc import AsyncGenerator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import structlog

from app.core.breaker import CircuitBreaker
from app.core.catalog import Target
from app.core.providers import Completion, Provider, ProviderError, StreamEvent
from app.core.schemas import ChatRequest

log = structlog.get_logger()


@dataclass(frozen=True)
class Attempt:
    provider: str
    outcome: str


class AllProvidersFailed(Exception):
    def __init__(self, attempts: list[Attempt]) -> None:
        super().__init__(", ".join(f"{a.provider}:{a.outcome}" for a in attempts))
        self.attempts = attempts


class UpstreamRejected(Exception):
    def __init__(self, provider: str, status: int, detail: str, attempts: list[Attempt]) -> None:
        super().__init__(f"{provider} rejected the request: {detail}")
        self.provider = provider
        self.status = status
        self.detail = detail
        self.attempts = attempts


@dataclass
class OpenedStream:
    target: Target
    attempts: list[Attempt]
    first: StreamEvent
    rest: AsyncGenerator[StreamEvent]


def upstream_body(req: ChatRequest, target: Target) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": target.model,
        "messages": [message.model_dump() for message in req.messages],
        "max_tokens": req.max_tokens,
        "temperature": req.temperature,
    }
    if req.top_p is not None:
        body["top_p"] = req.top_p
    return body


class Router:
    """Tries a model's targets in order, honouring circuit breakers and simulated outages."""

    def __init__(self, providers: Mapping[str, Provider], breakers: Mapping[str, CircuitBreaker]) -> None:
        self._providers = dict(providers)
        self._breakers = dict(breakers)

    def _skip_reason(self, target: Target, fail_provider: str | None) -> str | None:
        if target.provider == fail_provider:
            return "simulated"
        if not self._breakers[target.provider].allow():
            return "circuit_open"
        return None

    def _record_failure(self, target: Target, err: ProviderError, attempts: list[Attempt]) -> None:
        attempts.append(Attempt(target.provider, err.outcome))
        if err.status in (401, 403):
            log.error("provider_auth_failed", provider=target.provider, status=err.status)
        if not err.retryable:
            self._breakers[target.provider].record_success()  # the provider answered; the request was bad
            raise UpstreamRejected(target.provider, err.status or 400, err.detail, attempts) from err
        self._breakers[target.provider].record_failure()

    def _succeed(self, target: Target, attempts: list[Attempt]) -> None:
        self._breakers[target.provider].record_success()
        attempts.append(Attempt(target.provider, "ok"))

    async def complete(
        self, targets: Sequence[Target], req: ChatRequest, *, fail_provider: str | None = None
    ) -> tuple[Target, Completion, list[Attempt]]:
        attempts: list[Attempt] = []
        for target in targets:
            reason = self._skip_reason(target, fail_provider)
            if reason is not None:
                attempts.append(Attempt(target.provider, reason))
                continue
            try:
                completion = await self._providers[target.provider].complete(upstream_body(req, target))
            except ProviderError as err:
                self._record_failure(target, err, attempts)
                continue
            self._succeed(target, attempts)
            return target, completion, attempts
        raise AllProvidersFailed(attempts)

    async def open_stream(
        self, targets: Sequence[Target], req: ChatRequest, *, fail_provider: str | None = None
    ) -> OpenedStream:
        attempts: list[Attempt] = []
        for target in targets:
            reason = self._skip_reason(target, fail_provider)
            if reason is not None:
                attempts.append(Attempt(target.provider, reason))
                continue
            stream = self._providers[target.provider].stream(upstream_body(req, target))
            try:
                first = await anext(stream)
            except StopAsyncIteration:
                err = ProviderError(target.provider, "bad_response", retryable=True, detail="empty stream")
                self._record_failure(target, err, attempts)
                continue
            except ProviderError as err:
                await stream.aclose()
                self._record_failure(target, err, attempts)
                continue
            self._succeed(target, attempts)
            return OpenedStream(target=target, attempts=attempts, first=first, rest=stream)
        raise AllProvidersFailed(attempts)

    def report_midstream_failure(self, provider: str) -> None:
        self._breakers[provider].record_failure()

    def circuit_states(self) -> dict[str, str]:
        return {name: breaker.state for name, breaker in self._breakers.items()}
