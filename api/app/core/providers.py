import json
from collections.abc import AsyncGenerator, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

PROVIDER_TIMEOUT = httpx.Timeout(connect=3.0, read=10.0, write=10.0, pool=3.0)
_NOT_RETRYABLE = frozenset({400, 422})  # the request itself is bad; every provider would refuse it


class ProviderError(Exception):
    def __init__(
        self, provider: str, outcome: str, *, retryable: bool, status: int | None = None, detail: str = ""
    ) -> None:
        super().__init__(f"{provider}: {outcome} {detail}".strip())
        self.provider = provider
        self.outcome = outcome
        self.retryable = retryable
        self.status = status
        self.detail = detail


@dataclass(frozen=True)
class Completion:
    text: str
    finish_reason: str | None
    prompt_tokens: int | None
    completion_tokens: int | None


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class Finish:
    reason: str


@dataclass(frozen=True)
class UsageReport:
    prompt_tokens: int
    completion_tokens: int


StreamEvent = TextDelta | Finish | UsageReport


class Provider(Protocol):
    name: str

    async def complete(self, body: dict[str, Any]) -> Completion: ...

    def stream(self, body: dict[str, Any]) -> AsyncGenerator[StreamEvent]: ...


def _check_status(provider: str, status: int, text: str) -> None:
    if status == 200:
        return
    raise ProviderError(
        provider, str(status), retryable=status not in _NOT_RETRYABLE, status=status, detail=text[:300]
    )


def _parse_line(provider: str, line: str) -> list[StreamEvent] | None:
    """Events in one SSE line; None marks the end of the stream."""
    if not line.startswith("data:"):
        return []
    payload = line[5:].strip()
    if payload == "[DONE]":
        return None
    try:
        data = json.loads(payload)
    except ValueError as exc:
        raise ProviderError(provider, "bad_response", retryable=True, detail=payload[:200]) from exc
    if "error" in data:
        raise ProviderError(provider, "upstream_error", retryable=True, detail=str(data["error"])[:300])
    events: list[StreamEvent] = []
    for choice in data.get("choices") or []:
        content = (choice.get("delta") or {}).get("content")
        if content:
            events.append(TextDelta(content))
        if choice.get("finish_reason"):
            events.append(Finish(choice["finish_reason"]))
    usage = data.get("usage")
    if usage:
        events.append(UsageReport(int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))))
    return events


class OpenAICompatProvider:
    """Any provider speaking OpenAI's /chat/completions (Cerebras, OpenRouter)."""

    def __init__(
        self,
        name: str,
        base_url: str,
        api_key: str,
        client: httpx.AsyncClient,
        extra_headers: Mapping[str, str] | None = None,
    ) -> None:
        self.name = name
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._client = client
        self._headers = {"Authorization": f"Bearer {api_key}", **(extra_headers or {})}

    async def complete(self, body: dict[str, Any]) -> Completion:
        try:
            resp = await self._client.post(self._url, json={**body, "stream": False}, headers=self._headers)
        except httpx.TimeoutException as exc:
            raise ProviderError(self.name, "timeout", retryable=True, detail=str(exc)) from exc
        except httpx.TransportError as exc:
            raise ProviderError(self.name, "network_error", retryable=True, detail=str(exc)) from exc
        _check_status(self.name, resp.status_code, resp.text)
        try:
            data = resp.json()
            choice = data["choices"][0]
            usage = data.get("usage") or {}
            return Completion(
                text=choice["message"]["content"] or "",
                finish_reason=choice.get("finish_reason"),
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
            )
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
            raise ProviderError(self.name, "bad_response", retryable=True, detail=resp.text[:200]) from exc

    async def stream(self, body: dict[str, Any]) -> AsyncGenerator[StreamEvent]:
        payload = {**body, "stream": True, "stream_options": {"include_usage": True}}
        try:
            async with self._client.stream("POST", self._url, json=payload, headers=self._headers) as resp:
                if resp.status_code != 200:
                    await resp.aread()
                    _check_status(self.name, resp.status_code, resp.text)
                async for line in resp.aiter_lines():
                    events = _parse_line(self.name, line)
                    if events is None:
                        return
                    for event in events:
                        yield event
        except httpx.TimeoutException as exc:
            raise ProviderError(self.name, "timeout", retryable=True, detail=str(exc)) from exc
        except httpx.TransportError as exc:
            raise ProviderError(self.name, "network_error", retryable=True, detail=str(exc)) from exc
