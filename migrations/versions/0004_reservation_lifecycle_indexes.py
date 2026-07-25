"""Add indexes to optimize reservation lifecycle queries.

- Composite index on reservations(user_id, status) for fast "my active reservations" lookups
- Partial index on reservations(slot_id) WHERE status = 'active' for fast lifecycle transitions

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-21 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Composite index for "get user's active reservations" query pattern
    op.create_index(
        "ix_reservations_user_status",
        "reservations",
        ["user_id", "status"],
    )

    # Partial index for lifecycle transition: find active reservations to complete
    op.execute("""
        CREATE INDEX ix_reservations_active_slot
        ON reservations (slot_id)
        WHERE status = 'active'
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_reservations_active_slot")
    op.drop_index("ix_reservations_user_status", table_name="reservations")
