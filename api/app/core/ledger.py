from dataclasses import asdict, dataclass
from decimal import Decimal
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Usage

log = structlog.get_logger()


@dataclass(frozen=True)
class UsageRecord:
    key_id: UUID
    user_id: UUID
    model: str
    provider: str | None
    upstream_model: str | None
    prompt_tokens: int
    completion_tokens: int
    cost_usd: Decimal
    list_cost_saved_usd: Decimal
    cache_hit: bool
    status: str
    error_code: str | None
    latency_ms: int
    ttft_ms: int | None
    attempts: int


class Ledger:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def write(self, record: UsageRecord) -> bool:
        for attempt in (1, 2):
            try:
                async with self._sessions() as session, session.begin():
                    session.add(Usage(**asdict(record)))
                return True
            except Exception:  # a lost ledger row must never fail the request; it is logged in full
                if attempt == 2:
                    log.exception(
                        "ledger_write_failed", record={k: str(v) for k, v in asdict(record).items()}
                    )
        return False
