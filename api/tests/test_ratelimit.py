import asyncio

from redis.asyncio import Redis

from app.core.ratelimit import RateDecision, RateLimiter, rate_headers


class FakeClock:
    def __init__(self, ms: int = 1_000_000) -> None:
        self.ms = ms

    def __call__(self) -> int:
        return self.ms


async def test_allows_the_capacity_then_blocks_with_retry_after(redis: Redis) -> None:
    limiter = RateLimiter(redis, per_minute=20, clock=FakeClock())
    decisions = [await limiter.hit("k1") for _ in range(20)]
    assert all(d.allowed for d in decisions)
    assert decisions[-1].remaining == 0
    blocked = await limiter.hit("k1")
    assert not blocked.allowed
    assert blocked.retry_after_s == 3  # one token every 3 s at 20/min
    assert blocked.limit == 20


async def test_refills_over_time(redis: Redis) -> None:
    clock = FakeClock()
    limiter = RateLimiter(redis, per_minute=20, clock=clock)
    for _ in range(20):
        await limiter.hit("k1")
    clock.ms += 3_000
    assert (await limiter.hit("k1")).allowed
    assert not (await limiter.hit("k1")).allowed


async def test_keys_are_independent(redis: Redis) -> None:
    limiter = RateLimiter(redis, per_minute=1, clock=FakeClock())
    assert (await limiter.hit("a")).allowed
    assert (await limiter.hit("b")).allowed
    assert not (await limiter.hit("a")).allowed


async def test_concurrent_hits_never_exceed_the_capacity(redis: Redis) -> None:
    limiter = RateLimiter(redis, per_minute=20, clock=FakeClock())
    decisions = await asyncio.gather(*(limiter.hit("k1") for _ in range(50)))
    assert sum(d.allowed for d in decisions) == 20


async def test_bucket_key_expires_once_it_would_be_full(redis: Redis) -> None:
    await RateLimiter(redis, per_minute=20, clock=FakeClock()).hit("k1")
    ttl_ms = await redis.pttl("rl:k1")
    assert 0 < ttl_ms <= 61_000


def test_rate_headers_follow_openai_names() -> None:
    headers = rate_headers(RateDecision(allowed=True, limit=20, remaining=7, retry_after_s=0, reset_s=39))
    assert headers == {
        "x-ratelimit-limit-requests": "20",
        "x-ratelimit-remaining-requests": "7",
        "x-ratelimit-reset-requests": "39s",
    }
