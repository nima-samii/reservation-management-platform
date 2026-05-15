"""Replace full unique constraint on reservations.slot_id with a partial unique index
that only applies to ACTIVE reservations, allowing re-booking after cancellation.

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-15 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop the old full unique constraint — it blocks re-booking after cancellation
    op.drop_constraint("uq_reservations_slot", "reservations", type_="unique")

    # Partial unique index: only one ACTIVE reservation per slot is allowed.
    # Cancelled / completed rows do not conflict with new bookings.
    op.execute("""
        CREATE UNIQUE INDEX uq_reservations_slot_active
        ON reservations (slot_id)
        WHERE status = 'active'
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_reservations_slot_active")
    op.create_unique_constraint("uq_reservations_slot", "reservations", ["slot_id"])
