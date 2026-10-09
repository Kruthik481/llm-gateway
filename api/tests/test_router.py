import httpx
import pytest

from app.core.breaker import CircuitBreaker
from app.core.catalog import Target
from app.core.providers import OpenAICompatProvider, Provider, TextDelta
from app.core.router import AllProvidersFailed, Attempt, Router, UpstreamRejected
from app.core.schemas import ChatRequest
from tests.fakes import FakeUpstream, Reply, Status, StreamReply, Timeout

TARGETS = (
    Target("cerebras", "llama-3.3-70b"),
    Target("openrouter", "meta-llama/llama-3.3-70b-instruct:free"),
)
REQ = ChatRequest.model_validate(
    {
        "model": "llama-3.3-70b",
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 8,
        "temperature": 0,
    }
)


@pytest.fixture
def fake() -> FakeUpstream:
    return FakeUpstream()


@pytest.fixture
def router(fake: FakeUpstream) -> Router:
    client = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
    providers: dict[str, Provider] = {
        "cerebras": OpenAICompatProvider("cerebras", "https://api.cerebras.ai/v1", "k", client),
        "openrouter": OpenAICompatProvider("openrouter", "https://openrouter.ai/api/v1", "k", client),
    }
    return Router(providers, {name: CircuitBreaker() for name in providers})


async def test_uses_the_first_healthy_target(router: Router, fake: FakeUpstream) -> None:
    target, completion, attempts = await router.complete(TARGETS, REQ)
    assert target.provider == "cerebras"
    assert completion.text == "Hello there!"
    assert attempts == [Attempt("cerebras", "ok")]
    sent = fake.calls_to("cerebras")[0].body
    assert sent["model"] == "llama-3.3-70b"
    assert sent["temperature"] == 0
    assert sent["max_tokens"] == 8


async def test_falls_back_on_a_retryable_failure(router: Router, fake: FakeUpstream) -> None:
    fake.script("cerebras", Status(429))
    target, _, attempts = await router.complete(TARGETS, REQ)
    assert target.provider == "openrouter"
    assert attempts == [Attempt("cerebras", "429"), Attempt("openrouter", "ok")]
    assert fake.calls_to("openrouter")[0].body["model"] == "meta-llama/llama-3.3-70b-instruct:free"


async def test_a_400_is_not_retried(router: Router, fake: FakeUpstream) -> None:
    fake.script("cerebras", Status(400, "context too long"))
    with pytest.raises(UpstreamRejected) as exc:
        await router.complete(TARGETS, REQ)
    assert exc.value.provider == "cerebras"
    assert "context too long" in exc.value.detail
    assert fake.calls_to("openrouter") == []


async def test_reports_every_attempt_when_all_fail(router: Router, fake: FakeUpstream) -> None:
    fake.script("cerebras", Timeout())
    fake.script("openrouter", Status(503))
    with pytest.raises(AllProvidersFailed) as exc:
        await router.complete(TARGETS, REQ)
    assert exc.value.attempts == [Attempt("cerebras", "timeout"), Attempt("openrouter", "503")]


async def test_an_open_circuit_skips_the_provider(router: Router, fake: FakeUpstream) -> None:
    fake.script("cerebras", *[Status(500)] * 5)
    for _ in range(5):
        await router.complete(TARGETS, REQ)
    assert router.circuit_states()["cerebras"] == "open"
    calls_before = len(fake.calls_to("cerebras"))
    _, _, attempts = await router.complete(TARGETS, REQ)
    assert attempts[0] == Attempt("cerebras", "circuit_open")
    assert len(fake.calls_to("cerebras")) == calls_before


async def test_simulated_failure_skips_without_touching_the_breaker(
    router: Router, fake: FakeUpstream
) -> None:
    target, _, attempts = await router.complete(TARGETS, REQ, fail_provider="cerebras")
    assert target.provider == "openrouter"
    assert attempts[0] == Attempt("cerebras", "simulated")
    assert fake.calls_to("cerebras") == []
    assert router.circuit_states()["cerebras"] == "closed"


async def test_stream_falls_back_before_the_first_token(router: Router, fake: FakeUpstream) -> None:
    fake.script("cerebras", Timeout())
    fake.script("openrouter", StreamReply(pieces=["Hi", "!"]))
    opened = await router.open_stream(TARGETS, REQ)
    assert opened.target.provider == "openrouter"
    assert opened.first == TextDelta("Hi")
    rest = [event async for event in opened.rest]
    assert rest[0] == TextDelta("!")
    assert opened.attempts == [Attempt("cerebras", "timeout"), Attempt("openrouter", "ok")]


async def test_stream_failing_everywhere_raises(router: Router, fake: FakeUpstream) -> None:
    fake.script("cerebras", Status(500))
    fake.script("openrouter", Status(502))
    with pytest.raises(AllProvidersFailed):
        await router.open_stream(TARGETS, REQ)


async def test_midstream_failures_count_toward_the_breaker(router: Router) -> None:
    for _ in range(5):
        router.report_midstream_failure("cerebras")
    assert router.circuit_states() == {"cerebras": "open", "openrouter": "closed"}


async def test_reply_without_content_still_counts_as_success(router: Router, fake: FakeUpstream) -> None:
    fake.script("cerebras", Reply(text=""))
    _, completion, _ = await router.complete(TARGETS, REQ)
    assert completion.text == ""
