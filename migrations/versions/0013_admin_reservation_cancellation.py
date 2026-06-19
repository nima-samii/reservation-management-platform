"""Admin reservation cancellation — attribution columns.

reservations: + cancelled_by, cancellation_reason, cancelled_at.

These record who cancelled a reservation from the admin panel, why, and when.
All three are nullable so existing rows (and user-initiated cancellations, which
leave them NULL) remain valid. No data migration and no indexes are added — the
columns are written on the cancel action and read back only on the reservation
detail view, never filtered/sorted on.

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-19 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "reservations",
        sa.Column("cancelled_by", sa.String(128), nullable=True),
    )
    op.add_column(
        "reservations",
        sa.Column("cancellation_reason", sa.String(256), nullable=True),
    )
    op.add_column(
        "reservations",
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("reservations", "cancelled_at")
    op.drop_column("reservations", "cancellation_reason")
    op.drop_column("reservations", "cancelled_by")
