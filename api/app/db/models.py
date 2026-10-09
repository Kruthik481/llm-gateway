from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Numeric,
    SmallInteger,
    String,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    github_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    login: Mapped[str] = mapped_column(String(100))
    avatar_url: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(40))
    prefix: Mapped[str] = mapped_column(String(12))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Usage(Base):
    __tablename__ = "usage"
    __table_args__ = (
        CheckConstraint("status in ('ok', 'error', 'partial')", name="usage_status_check"),
        Index("ix_usage_user_created", "user_id", text("created_at DESC")),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    key_id: Mapped[UUID] = mapped_column(ForeignKey("api_keys.id"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    model: Mapped[str] = mapped_column(String(100))
    provider: Mapped[str | None] = mapped_column(String(40))
    upstream_model: Mapped[str | None] = mapped_column(String(200))
    prompt_tokens: Mapped[int]
    completion_tokens: Mapped[int]
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 8))
    list_cost_saved_usd: Mapped[Decimal] = mapped_column(Numeric(12, 8))
    cache_hit: Mapped[bool]
    status: Mapped[str] = mapped_column(String(10))
    error_code: Mapped[str | None] = mapped_column(String(40))
    latency_ms: Mapped[int]
    ttft_ms: Mapped[int | None]
    attempts: Mapped[int] = mapped_column(SmallInteger)
