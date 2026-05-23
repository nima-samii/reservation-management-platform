"""Add participation score system.

- users.participation_score: cached score column (INTEGER, default 0)
- score_transactions: immutable audit ledger for all score events

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-23 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── users: cached score column ────────────────────────────────────────────
    op.add_column(
        "users",
        sa.Column(
            "participation_score",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )

    # ── score_transactions: immutable ledger ──────────────────────────────────
    op.create_table(
        "score_transactions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reservation_id", UUID(as_uuid=True), sa.ForeignKey("reservations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("transaction_type", sa.String(40), nullable=False),
        sa.Column("score_delta", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(256), nullable=True),
        sa.Column("meta", JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )

    op.create_index("ix_score_transactions_user_id", "score_transactions", ["user_id"])
    op.create_index("ix_score_transactions_reservation_id", "score_transactions", ["reservation_id"])
    op.create_index("ix_score_transactions_type", "score_transactions", ["transaction_type"])
    # Composite index for paginated score history queries (most common admin/API access pattern)
    op.create_index(
        "ix_score_transactions_user_created",
        "score_transactions",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_score_transactions_user_created", table_name="score_transactions")
    op.drop_index("ix_score_transactions_type", table_name="score_transactions")
    op.drop_index("ix_score_transactions_reservation_id", table_name="score_transactions")
    op.drop_index("ix_score_transactions_user_id", table_name="score_transactions")
    op.drop_table("score_transactions")
    op.drop_column("users", "participation_score")
