"""Add channel_id to reservation_slots (per-channel slot model)

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-15 00:00:00.000000

NOTE: This migration clears existing reservation_slots and reservations data.
Slots are regenerated automatically at app startup by the APScheduler job.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Clear existing data — slots will be regenerated per-channel at startup.
    # Reservations must be deleted first due to FK constraint.
    op.execute("DELETE FROM reservations")
    op.execute("DELETE FROM reservation_slots")

    # Drop old single-column unique constraint on slot_datetime
    op.drop_constraint("uq_slot_datetime", "reservation_slots", type_="unique")

    # Add channel_id column (table is empty so NOT NULL is allowed without a default)
    op.add_column(
        "reservation_slots",
        sa.Column("channel_id", postgresql.UUID(as_uuid=True), nullable=False),
    )

    # Foreign key to channels
    op.create_foreign_key(
        "fk_reservation_slots_channel_id",
        "reservation_slots",
        "channels",
        ["channel_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    # Index for efficient per-channel queries
    op.create_index(
        "ix_reservation_slots_channel_id",
        "reservation_slots",
        ["channel_id"],
    )

    # New composite unique constraint: one slot per (datetime, channel)
    op.create_unique_constraint(
        "uq_slot_datetime_channel",
        "reservation_slots",
        ["slot_datetime", "channel_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_slot_datetime_channel", "reservation_slots", type_="unique")
    op.drop_index("ix_reservation_slots_channel_id", "reservation_slots")
    op.drop_constraint("fk_reservation_slots_channel_id", "reservation_slots", type_="foreignkey")
    op.drop_column("reservation_slots", "channel_id")
    op.create_unique_constraint("uq_slot_datetime", "reservation_slots", ["slot_datetime"])
