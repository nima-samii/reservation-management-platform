"""Score-change notifications — track per-transaction delivery state.

score_transactions: + notified_at, notify_status.

`notify_status` lifecycle: pending → sending → sent | failed | skipped.
`notified_at` is set once a terminal outcome is reached and is the idempotency
guard (a transaction with notify_status='pending' has never been claimed).
Partial index on the pending status keeps the future reconcile lookup cheap.

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-19 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "score_transactions",
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "score_transactions",
        sa.Column(
            "notify_status",
            sa.String(20),
            nullable=False,
            server_default="pending",
        ),
    )
    # Cheap lookup of not-yet-delivered transactions (reconcile / debugging).
    op.create_index(
        "ix_score_transactions_notify_status",
        "score_transactions",
        ["notify_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_score_transactions_notify_status", table_name="score_transactions")
    op.drop_column("score_transactions", "notify_status")
    op.drop_column("score_transactions", "notified_at")
