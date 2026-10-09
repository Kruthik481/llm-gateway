from dataclasses import asdict
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.control.auth import require_user
from app.control.schemas import (
    BudgetOut,
    KeyCreatedOut,
    KeyCreateIn,
    KeyOut,
    MeOut,
    PublicStatsOut,
    RecentOut,
    SummaryOut,
)
from app.core.errors import GatewayError
from app.db.models import User
from app.db.repo import MAX_ACTIVE_KEYS, KeyLimitReached, create_key, list_keys, revoke_key
from app.db.usage_queries import public_stats, recent_usage, usage_summary
from app.state import GatewayState, get_state

router = APIRouter(prefix="/control", tags=["control"])
StateDep = Annotated[GatewayState, Depends(get_state)]
UserDep = Annotated[User, Depends(require_user)]
PUBLIC_STATS_TTL_S = 30


@router.get("/me")
async def me(user: UserDep) -> MeOut:
    return MeOut(id=user.id, github_id=user.github_id, login=user.login, avatar_url=user.avatar_url)


@router.get("/keys")
async def get_keys(user: UserDep, state: StateDep) -> list[KeyOut]:
    async with state.sessions() as session:
        rows = await list_keys(session, user.id)
    return [KeyOut(**asdict(row)) for row in rows]


@router.post("/keys", status_code=201)
async def post_key(body: KeyCreateIn, user: UserDep, state: StateDep) -> KeyCreatedOut:
    try:
        async with state.sessions() as session, session.begin():
            key, raw = await create_key(session, user_id=user.id, name=body.name)
    except KeyLimitReached as exc:
        raise GatewayError(
            409, "key_limit", f"You can have at most {MAX_ACTIVE_KEYS} active keys. Revoke one first."
        ) from exc
    return KeyCreatedOut(id=key.id, name=key.name, prefix=key.prefix, created_at=key.created_at, key=raw)


@router.delete("/keys/{key_id}", status_code=204)
async def delete_key(key_id: UUID, user: UserDep, state: StateDep) -> Response:
    async with state.sessions() as session, session.begin():
        key_hash = await revoke_key(session, user_id=user.id, key_id=key_id)
    if key_hash is None:
        raise GatewayError(404, "key_not_found", "No active key with that id.")
    await state.resolver.forget(key_hash)
    return Response(status_code=204)


@router.get("/usage/summary")
async def get_summary(
    user: UserDep, state: StateDep, days: Annotated[int, Query(ge=1, le=30)] = 14
) -> SummaryOut:
    async with state.sessions() as session:
        summary = await usage_summary(session, user.id, days=days, today=state.budget.today())
    used = await state.budget.used_today(str(user.id))
    return SummaryOut.model_validate(
        {**asdict(summary), "budget": BudgetOut(used=used, limit=state.settings.user_daily_tokens)}
    )


@router.get("/usage/recent")
async def get_recent(
    user: UserDep, state: StateDep, limit: Annotated[int, Query(ge=1, le=100)] = 50
) -> list[RecentOut]:
    async with state.sessions() as session:
        rows = await recent_usage(session, user.id, limit=limit)
    return [RecentOut(**asdict(row)) for row in rows]


@router.get("/stats/public")
async def get_public_stats(state: StateDep) -> PublicStatsOut:
    cached = await state.redis.get("stats:public")
    if cached is not None:
        return PublicStatsOut.model_validate_json(cached)
    async with state.sessions() as session:
        stats = PublicStatsOut(**asdict(await public_stats(session, today=state.budget.today())))
    await state.redis.set("stats:public", stats.model_dump_json(), ex=PUBLIC_STATS_TTL_S)
    return stats
