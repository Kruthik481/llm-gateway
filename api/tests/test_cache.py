from redis.asyncio import Redis

from app.core.cache import (
    CACHE_TTL_S,
    MAX_CACHED_BYTES,
    CachedCompletion,
    ResponseCache,
    cache_key,
    is_cacheable,
    replay_chunks,
)
from app.core.schemas import ChatRequest


def req(**overrides: object) -> ChatRequest:
    body: dict[str, object] = {
        "model": "gpt-oss-120b",
        "messages": [{"role": "user", "content": "What is 2+2?"}],
        "temperature": 0,
    }
    body.update(overrides)
    return ChatRequest.model_validate(body)


VALUE = CachedCompletion("4", "stop", 9, 1, "groq", "gpt-oss-120b")


def test_only_deterministic_unbypassed_requests_are_cacheable() -> None:
    assert is_cacheable(req(), bypass=False)
    assert not is_cacheable(req(temperature=0.7), bypass=False)
    assert not is_cacheable(req(), bypass=True)


def test_key_is_stable_and_ignores_stream_flags() -> None:
    assert cache_key("u1", req()) == cache_key("u1", req(stream=True, stream_options={"include_usage": True}))
    assert cache_key("u1", req()).startswith("cache:u1:")


def test_key_is_scoped_per_user() -> None:
    assert cache_key("u1", req()) != cache_key("u2", req())


def test_key_changes_with_anything_that_changes_the_answer() -> None:
    base = cache_key("u1", req())
    assert cache_key("u1", req(max_tokens=10)) != base
    assert cache_key("u1", req(top_p=0.5)) != base
    assert cache_key("u1", req(model="gpt-oss-20b")) != base
    assert cache_key("u1", req(messages=[{"role": "user", "content": "What is 2+2? "}])) != base


async def test_round_trip_with_a_day_ttl(redis: Redis) -> None:
    cache = ResponseCache(redis)
    key = cache_key("u1", req())
    assert await cache.get(key) is None
    assert await cache.put(key, VALUE)
    assert await cache.get(key) == VALUE
    assert 0 < await redis.ttl(key) <= CACHE_TTL_S


async def test_oversized_answers_are_not_stored(redis: Redis) -> None:
    cache = ResponseCache(redis)
    big = CachedCompletion("x" * MAX_CACHED_BYTES, "stop", 1, 1, "groq", "m")
    assert not await cache.put("cache:u1:big", big)
    assert await redis.exists("cache:u1:big") == 0


def test_replay_chunks_cover_the_text_in_order() -> None:
    text = "a" * 95
    chunks = replay_chunks(text)
    assert [len(c) for c in chunks] == [40, 40, 15]
    assert "".join(chunks) == text
    assert replay_chunks("") == []
