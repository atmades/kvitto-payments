"""Create tariffs and payments tables

Revision ID: 0001
Revises:
Create Date: 2026-10-19
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
        "tariffs",
        sa.Column("id", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=100), nullable=False),
        # Price in kopecks.
        sa.Column("price", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "payments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tariff_id", sa.String(length=20), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("method", sa.String(length=20), nullable=False),
        sa.Column("installment_months", sa.Integer(), nullable=True),
        # Amount and discount in kopecks.
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("discount", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("schedule", sa.JSON(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tariff_id"], ["tariffs.id"]),
        sa.PrimaryKeyConstraint("id"),
        # The database-level guarantee that one key never creates two payments.
        sa.UniqueConstraint("idempotency_key"),
    )


def downgrade() -> None:
    op.drop_table("payments")
    op.drop_table("tariffs")
