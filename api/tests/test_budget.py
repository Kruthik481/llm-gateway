import asyncio
from datetime import date

import pytest
from redis.asyncio import Redis

from app.core.budget import (
    COUNTER_TTL_S,
    Budget,
    BudgetExceeded,
    estimate_completion_tokens,
    estimate_prompt_tokens,
    estimate_tokens,
)

DAY = date(2026, 10, 9)


def make_budget(redis: Redis, user_limit: int = 1_000, global_limit: int = 10_000) -> Budget:
    return Budget(redis, user_limit=user_limit, global_limit=global_limit, today=lambda: DAY)


def test_estimates_are_pessimistic_for_prompts() -> None:
    assert estimate_prompt_tokens(10) == 4
    assert estimate_completion_tokens("abcde") == 2
    assert estimate_tokens(prompt_chars=9, max_tokens=100) == 103


async def test_reserve_counts_against_user_and_global(redis: Redis) -> None:
    budget = make_budget(redis)
    reservation = await budget.reserve("u1", 300)
    assert reservation.amount == 300
    assert await budget.used_today("u1") == 300
    assert int(await redis.get("budget:global:2026-10-09") or 0) == 300
    assert 0 < await redis.ttl("budget:user:u1:2026-10-09") <= COUNTER_TTL_S


async def test_user_budget_is_enforced_without_partial_reservation(redis: Redis) -> None:
    budget = make_budget(redis, user_limit=500)
    await budget.reserve("u1", 400)
    with pytest.raises(BudgetExceeded) as exc:
        await budget.reserve("u1", 200)
    assert exc.value.scope == "user"
    assert await budget.used_today("u1") == 400
    assert int(await redis.get("budget:global:2026-10-09") or 0) == 400


async def test_global_cap_is_enforced(redis: Redis) -> None:
    budget = make_budget(redis, user_limit=1_000, global_limit=600)
    await budget.reserve("u1", 500)
    with pytest.raises(BudgetExceeded) as exc:
        await budget.reserve("u2", 200)
    assert exc.value.scope == "global"
    assert await budget.used_today("u2") == 0


async def test_settle_refunds_the_unused_part(redis: Redis) -> None:
    budget = make_budget(redis)
    reservation = await budget.reserve("u1", 300)
    await budget.settle(reservation, actual_tokens=120)
    assert await budget.used_today("u1") == 120
    assert int(await redis.get("budget:global:2026-10-09") or 0) == 120


async def test_settle_charges_extra_when_actual_exceeds_reservation(redis: Redis) -> None:
    budget = make_budget(redis)
    reservation = await budget.reserve("u1", 100)  # e.g. a Hindi prompt undercounted at chars/3
    await budget.settle(reservation, actual_tokens=180)
    assert await budget.used_today("u1") == 180


async def test_settle_never_goes_below_zero(redis: Redis) -> None:
    budget = make_budget(redis)
    reservation = await budget.reserve("u1", 100)
    await redis.set("budget:user:u1:2026-10-09", 10, keepttl=True)
    await budget.settle(reservation, actual_tokens=0)
    assert await budget.used_today("u1") == 0


async def test_settle_leaves_an_expired_counter_alone(redis: Redis) -> None:
    budget = make_budget(redis)
    reservation = await budget.reserve("u1", 100)
    await redis.delete("budget:user:u1:2026-10-09")
    await budget.settle(reservation, actual_tokens=0)
    assert await redis.exists("budget:user:u1:2026-10-09") == 0


async def test_concurrent_reservations_admit_exactly_what_fits(redis: Redis) -> None:
    budget = make_budget(redis, user_limit=3_000, global_limit=1_000_000)

    async def attempt() -> bool:
        try:
            await budget.reserve("u1", 100)
            return True
        except BudgetExceeded:
            return False

    results = await asyncio.gather(*(attempt() for _ in range(50)))
    assert results.count(True) == 30
    assert await budget.used_today("u1") == 3_000


async def test_counters_roll_over_with_the_utc_day(redis: Redis) -> None:
    day = {"value": DAY}
    budget = Budget(redis, user_limit=100, global_limit=1_000, today=lambda: day["value"])
    await budget.reserve("u1", 100)
    day["value"] = date(2026, 10, 10)
    await budget.reserve("u1", 100)
    assert await budget.used_today("u1") == 100
