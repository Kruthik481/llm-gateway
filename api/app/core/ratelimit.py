import math
import time
from collections.abc import Callable
from dataclasses import dataclass

from redis.asyncio import Redis

WINDOW_MS = 60_000

# KEYS[1] bucket hash; ARGV: capacity, refill rate (tokens per ms), now (ms)
_BUCKET_SCRIPT = """
local capacity = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local state = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens = tonumber(state[1]) or capacity
local ts = tonumber(state[2]) or now
tokens = math.min(capacity, tokens + math.max(0, now - ts) * rate)
local allowed = 0
if tokens >= 1 then
  tokens = tokens - 1
  allowed = 1
end
redis.call('HSET', KEYS[1], 'tokens', tostring(tokens), 'ts', tostring(now))
redis.call('PEXPIRE', KEYS[1], math.ceil(capacity / rate) + 1000)
local retry_ms = 0
if allowed == 0 then
  retry_ms = math.ceil((1 - tokens) / rate)
end
return {allowed, math.floor(tokens), retry_ms, math.ceil((capacity - tokens) / rate)}
"""


@dataclass(frozen=True)
class RateDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after_s: int
    reset_s: int


def _epoch_ms() -> int:
    return int(time.time() * 1000)


def rate_headers(decision: RateDecision) -> dict[str, str]:
    return {
        "x-ratelimit-limit-requests": str(decision.limit),
        "x-ratelimit-remaining-requests": str(decision.remaining),
        "x-ratelimit-reset-requests": f"{decision.reset_s}s",
    }


class RateLimiter:
    def __init__(self, redis: Redis, per_minute: int, clock: Callable[[], int] = _epoch_ms) -> None:
        self._script = redis.register_script(_BUCKET_SCRIPT)
        self._capacity = per_minute
        self._rate = per_minute / WINDOW_MS
        self._clock = clock

    async def hit(self, key_id: str) -> RateDecision:
        allowed, remaining, retry_ms, reset_ms = await self._script(
            keys=[f"rl:{key_id}"], args=[self._capacity, repr(self._rate), self._clock()]
        )
        return RateDecision(
            allowed=bool(allowed),
            limit=self._capacity,
            remaining=int(remaining),
            retry_after_s=math.ceil(int(retry_ms) / 1000),
            reset_s=math.ceil(int(reset_ms) / 1000),
        )
