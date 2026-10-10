import pytest
from pydantic import ValidationError

from app.core.schemas import MAX_PROMPT_CHARS, ChatRequest


def req(**overrides: object) -> ChatRequest:
    body: dict[str, object] = {"model": "gpt-oss-120b", "messages": [{"role": "user", "content": "hi"}]}
    body.update(overrides)
    return ChatRequest.model_validate(body)


def test_defaults_follow_openai() -> None:
    r = req()
    assert (r.temperature, r.top_p, r.max_tokens, r.stream, r.include_usage) == (
        1.0,
        None,
        1024,
        False,
        False,
    )


def test_unknown_fields_are_ignored() -> None:
    assert req(user="abc", seed=7).model == "gpt-oss-120b"


@pytest.mark.parametrize(
    "overrides",
    [
        {"max_tokens": 0},
        {"max_tokens": 4097},
        {"temperature": 2.5},
        {"top_p": 0},
        {"messages": []},
        {"messages": [{"role": "tool", "content": "x"}]},
        {"messages": [{"role": "user", "content": [{"type": "text", "text": "x"}]}]},
    ],
)
def test_invalid_requests_are_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        req(**overrides)


def test_prompt_size_is_capped() -> None:
    with pytest.raises(ValidationError, match="too long"):
        req(messages=[{"role": "user", "content": "x" * (MAX_PROMPT_CHARS + 1)}])


def test_prompt_chars_and_include_usage() -> None:
    r = req(
        messages=[{"role": "system", "content": "abc"}, {"role": "user", "content": "de"}],
        stream=True,
        stream_options={"include_usage": True},
    )
    assert r.prompt_chars() == 5
    assert r.include_usage is True
