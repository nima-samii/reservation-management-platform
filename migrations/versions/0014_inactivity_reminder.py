"""Inactivity reservation reminder — user reservation/reminder timestamps.

users: + last_reservation_at, last_inactivity_reminder_sent_at.

`last_reservation_at` is refreshed to now() every time a reservation is
successfully created (never on cancellation) — it is the reset anchor for the
reminder cycle. `last_inactivity_reminder_sent_at` records the last time an
inactivity reminder was delivered; together with `last_reservation_at` it lets
the eligibility query re-fire every INACTIVITY_REMINDER_THRESHOLD_DAYS period
until the user reserves again, without a separate notification-log table.
Both nullable — existing users may have never had a reservation or a reminder.

Backfills `last_reservation_at` for existing users from their most recent
non-cancelled reservation's `created_at`, so users with reservation history
predating this migration are correctly eligible without waiting for a new
booking. Index on `last_reservation_at` supports the daily eligibility scan.

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-09 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("last_reservation_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "last_inactivity_reminder_sent_at", sa.DateTime(timezone=True), nullable=True
        ),
    )

    op.execute(
        """
        UPDATE users u
        SET last_reservation_at = r.max_created_at
        FROM (
            SELECT user_id, MAX(created_at) AS max_created_at
            FROM reservations
            WHERE status != 'cancelled'
            GROUP BY user_id
        ) r
        WHERE u.id = r.user_id
        """
    )

    op.create_index(
        "ix_users_last_reservation_at",
        "users",
        ["last_reservation_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_users_last_reservation_at", table_name="users")
    op.drop_column("users", "last_inactivity_reminder_sent_at")
    op.drop_column("users", "last_reservation_at")
