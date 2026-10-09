from typing import Any

import httpx
import pytest

from app.core.providers import (
    Completion,
    Finish,
    OpenAICompatProvider,
    ProviderError,
    StreamEvent,
    TextDelta,
    UsageReport,
)
from tests.fakes import ConnectFail, FakeUpstream, Reply, Status, StreamReply, Timeout

BODY: dict[str, Any] = {
    "model": "llama-3.3-70b",
    "messages": [{"role": "user", "content": "hi"}],
    "max_tokens": 16,
}


@pytest.fixture
def fake() -> FakeUpstream:
    return FakeUpstream()


def cerebras(fake: FakeUpstream) -> OpenAICompatProvider:
    client = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
    return OpenAICompatProvider("cerebras", "https://api.cerebras.ai/v1", "csk-test", client)


async def collect(provider: OpenAICompatProvider) -> list[StreamEvent]:
    return [event async for event in provider.stream(BODY)]


async def test_complete_parses_text_and_usage(fake: FakeUpstream) -> None:
    fake.script("cerebras", Reply(text="Hi!", prompt_tokens=5, completion_tokens=2))
    assert await cerebras(fake).complete(BODY) == Completion("Hi!", "stop", 5, 2)


async def test_complete_sends_the_key_and_extra_headers(fake: FakeUpstream) -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
    provider = OpenAICompatProvider(
        "openrouter",
        "https://openrouter.ai/api/v1",
        "sk-or",
        client,
        extra_headers={"X-Title": "LLM Gateway"},
    )
    await provider.complete(BODY)
    call = fake.calls_to("openrouter")[0]
    assert call.headers["authorization"] == "Bearer sk-or"
    assert call.headers["x-title"] == "LLM Gateway"
    assert call.body["model"] == "llama-3.3-70b"


async def test_missing_usage_is_reported_as_unknown(fake: FakeUpstream) -> None:
    fake.script("cerebras", Reply(prompt_tokens=None, completion_tokens=None))
    result = await cerebras(fake).complete(BODY)
    assert (result.prompt_tokens, result.completion_tokens) == (None, None)


@pytest.mark.parametrize(
    ("code", "retryable"), [(429, True), (500, True), (503, True), (401, True), (400, False), (422, False)]
)
async def test_status_codes_are_classified(fake: FakeUpstream, code: int, retryable: bool) -> None:
    fake.script("cerebras", Status(code))
    with pytest.raises(ProviderError) as exc:
        await cerebras(fake).complete(BODY)
    assert exc.value.outcome == str(code)
    assert exc.value.retryable is retryable
    assert exc.value.status == code


@pytest.mark.parametrize(("behavior", "outcome"), [(Timeout(), "timeout"), (ConnectFail(), "network_error")])
async def test_transport_failures_are_retryable(
    fake: FakeUpstream, behavior: Timeout | ConnectFail, outcome: str
) -> None:
    fake.script("cerebras", behavior)
    with pytest.raises(ProviderError) as exc:
        await cerebras(fake).complete(BODY)
    assert (exc.value.outcome, exc.value.retryable) == (outcome, True)


async def test_stream_yields_text_finish_and_usage(fake: FakeUpstream) -> None:
    fake.script("cerebras", StreamReply(pieces=["Hel", "lo"], prompt_tokens=7))
    events = await collect(cerebras(fake))
    assert events == [TextDelta("Hel"), TextDelta("lo"), Finish("stop"), UsageReport(7, 2)]
    sent = fake.calls_to("cerebras")[0].body
    assert sent["stream"] is True
    assert sent["stream_options"] == {"include_usage": True}


async def test_stream_error_status_raises_before_any_event(fake: FakeUpstream) -> None:
    fake.script("cerebras", Status(429))
    stream = cerebras(fake).stream(BODY)
    with pytest.raises(ProviderError) as exc:
        await anext(stream)
    assert exc.value.outcome == "429"


async def test_stream_connection_drop_raises_after_some_events(fake: FakeUpstream) -> None:
    fake.script("cerebras", StreamReply(pieces=["a", "b", "c"], fail_after=2))
    seen: list[StreamEvent] = []
    with pytest.raises(ProviderError) as exc:
        async for event in cerebras(fake).stream(BODY):
            seen.append(event)
    assert seen == [TextDelta("a"), TextDelta("b")]
    assert exc.value.retryable


async def test_stream_in_band_error_raises(fake: FakeUpstream) -> None:
    fake.script("cerebras", StreamReply(pieces=["a", "b"], error_chunk_after=1))
    with pytest.raises(ProviderError) as exc:
        await collect(cerebras(fake))
    assert exc.value.outcome == "upstream_error"
