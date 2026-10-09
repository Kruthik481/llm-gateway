"""initial schema: users, api_keys, usage

Revision ID: 0001
Revises:
Create Date: 2026-10-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("github_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("login", sa.String(100), nullable=False),
        sa.Column("avatar_url", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(40), nullable=False),
        sa.Column("prefix", sa.String(12), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_api_keys_user_id", "api_keys", ["user_id"])
    op.create_table(
        "usage",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("key_id", sa.Uuid(), sa.ForeignKey("api_keys.id"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("provider", sa.String(40), nullable=True),
        sa.Column("upstream_model", sa.String(200), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(12, 8), nullable=False),
        sa.Column("list_cost_saved_usd", sa.Numeric(12, 8), nullable=False),
        sa.Column("cache_hit", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("error_code", sa.String(40), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("ttft_ms", sa.Integer(), nullable=True),
        sa.Column("attempts", sa.SmallInteger(), nullable=False),
        sa.CheckConstraint("status in ('ok', 'error', 'partial')", name="usage_status_check"),
    )
    op.create_index("ix_usage_user_created", "usage", ["user_id", sa.text("created_at DESC")])


def downgrade() -> None:
    op.drop_index("ix_usage_user_created", table_name="usage")
    op.drop_table("usage")
    op.drop_index("ix_api_keys_user_id", table_name="api_keys")
    op.drop_table("api_keys")
    op.drop_table("users")
