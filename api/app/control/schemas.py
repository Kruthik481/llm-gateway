from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class MeOut(BaseModel):
    id: UUID
    github_id: int
    login: str
    avatar_url: str


class KeyCreateIn(BaseModel):
    name: str = Field(max_length=40)

    @field_validator("name")
    @classmethod
    def _strip(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("name must not be blank")
        return stripped


class KeyOut(BaseModel):
    id: UUID
    name: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None
    requests_24h: int


class KeyCreatedOut(BaseModel):
    id: UUID
    name: str
    prefix: str
    created_at: datetime
    key: str


class DayOut(BaseModel):
    day: date
    requests: int
    tokens: int


class ModelCostOut(BaseModel):
    model: str
    cost_usd: Decimal


class ProviderOut(BaseModel):
    provider: str
    requests: int


class PercentilesOut(BaseModel):
    p50: float | None
    p95: float | None


class BudgetOut(BaseModel):
    used: int
    limit: int


class SummaryOut(BaseModel):
    days: list[DayOut]
    cost_by_model: list[ModelCostOut]
    cache_saved_usd: Decimal
    providers: list[ProviderOut]
    fallbacks: int
    latency_ms: PercentilesOut
    ttft_ms: PercentilesOut
    budget: BudgetOut


class RecentOut(BaseModel):
    created_at: datetime
    key_prefix: str
    model: str
    provider: str | None
    prompt_tokens: int
    completion_tokens: int
    cost_usd: Decimal
    cache_hit: bool
    status: str
    latency_ms: int
    ttft_ms: int | None
    attempts: int


class PublicStatsOut(BaseModel):
    requests_today: int
    cache_hit_rate: float
    fallbacks_today: int
