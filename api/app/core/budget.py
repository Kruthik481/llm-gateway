import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal

from redis.asyncio import Redis

COUNTER_TTL_S = 48 * 3600

# KEYS: user counter, global counter. ARGV: amount, user limit, global limit, ttl seconds.
_RESERVE = """
local amount = tonumber(ARGV[1])
local user_used = tonumber(redis.call('GET', KEYS[1]) or '0')
local global_used = tonumber(redis.call('GET', KEYS[2]) or '0')
if user_used + amount > tonumber(ARGV[2]) then return {0, 'user'} end
if global_used + amount > tonumber(ARGV[3]) then return {0, 'global'} end
redis.call('INCRBY', KEYS[1], amount)
redis.call('EXPIRE', KEYS[1], ARGV[4])
redis.call('INCRBY', KEYS[2], amount)
redis.call('EXPIRE', KEYS[2], ARGV[4])
return {1, 'ok'}
"""

# KEYS: user counter, global counter. ARGV: delta = reserved - actual (negative charges extra).
_SETTLE = """
local delta = tonumber(ARGV[1])
for i = 1, 2 do
  if redis.call('EXISTS', KEYS[i]) == 1 then
    local next_value = math.max(0, tonumber(redis.call('GET', KEYS[i])) - delta)
    redis.call('SET', KEYS[i], next_value, 'KEEPTTL')
  end
end
return 1
"""


def estimate_prompt_tokens(prompt_chars: int) -> int:
    return math.ceil(prompt_chars / 3)


def estimate_completion_tokens(text: str) -> int:
    return math.ceil(len(text) / 4)


def estimate_tokens(prompt_chars: int, max_tokens: int) -> int:
    return estimate_prompt_tokens(prompt_chars) + max_tokens


@dataclass(frozen=True)
class Reservation:
    user_key: str
    global_key: str
    amount: int


class BudgetExceeded(Exception):
    def __init__(self, scope: Literal["user", "global"]) -> None:
        super().__init__(scope)
        self.scope: Literal["user", "global"] = scope


def _utc_today() -> date:
    return datetime.now(UTC).date()


class Budget:
    """Daily token budgets per user plus one global cap, reserved up front and settled afterwards."""

    def __init__(
        self, redis: Redis, *, user_limit: int, global_limit: int, today: Callable[[], date] = _utc_today
    ) -> None:
        self._redis = redis
        self._reserve = redis.register_script(_RESERVE)
        self._settle = redis.register_script(_SETTLE)
        self._user_limit = user_limit
        self._global_limit = global_limit
        self._today = today

    def today(self) -> date:
        return self._today()

    def _keys(self, user_id: str) -> tuple[str, str]:
        day = self._today().isoformat()
        return f"budget:user:{user_id}:{day}", f"budget:global:{day}"

    async def reserve(self, user_id: str, amount: int) -> Reservation:
        user_key, global_key = self._keys(user_id)
        ok, scope = await self._reserve(
            keys=[user_key, global_key], args=[amount, self._user_limit, self._global_limit, COUNTER_TTL_S]
        )
        if not int(ok):
            raise BudgetExceeded("user" if scope == "user" else "global")
        return Reservation(user_key=user_key, global_key=global_key, amount=amount)

    async def settle(self, reservation: Reservation, actual_tokens: int) -> None:
        await self._settle(
            keys=[reservation.user_key, reservation.global_key], args=[reservation.amount - actual_tokens]
        )

    async def used_today(self, user_id: str) -> int:
        return int(await self._redis.get(self._keys(user_id)[0]) or 0)
