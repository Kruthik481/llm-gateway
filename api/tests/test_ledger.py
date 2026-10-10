from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from structlog.testing import capture_logs

from app.core.ledger import Ledger, UsageRecord
from app.core.tasks import TaskTracker
from app.db.models import Usage
from app.db.repo import KeyIdentity
from tests.helpers import new_key, new_user


def record(identity: KeyIdentity) -> UsageRecord:
    return UsageRecord(
        key_id=identity.key_id,
        user_id=identity.user_id,
        model="gpt-oss-120b",
        provider="groq",
        upstream_model="gpt-oss-120b",
        prompt_tokens=3,
        completion_tokens=2,
        cost_usd=Decimal("0.00000495"),
        list_cost_saved_usd=Decimal(0),
        cache_hit=False,
        status="ok",
        error_code=None,
        latency_ms=50,
        ttft_ms=None,
        attempts=1,
    )


async def test_write_inserts_one_row(sessions: async_sessionmaker[AsyncSession]) -> None:
    user = await new_user(sessions)
    _, identity = await new_key(sessions, user.id)
    assert await Ledger(sessions).write(record(identity))
    async with sessions() as s:
        row = (await s.execute(select(Usage))).scalar_one()
    assert row.cost_usd == Decimal("0.00000495")


async def test_write_failure_is_retried_once_then_logged(sessions: async_sessionmaker[AsyncSession]) -> None:
    ghost = KeyIdentity(key_id=uuid4(), user_id=uuid4(), prefix="lgw_ghost")  # violates foreign keys
    with capture_logs() as logs:
        assert not await Ledger(sessions).write(record(ghost))
    assert [entry["event"] for entry in logs] == ["ledger_write_failed"]


async def test_task_tracker_drains_and_logs_failures() -> None:
    tracker = TaskTracker()
    done: list[int] = []

    async def ok() -> None:
        done.append(1)

    async def boom() -> None:
        raise RuntimeError("nope")

    with capture_logs() as logs:
        tracker.spawn(ok())
        tracker.spawn(boom())
        await tracker.drain()
    assert done == [1]
    assert [entry["event"] for entry in logs] == ["background_task_failed"]
