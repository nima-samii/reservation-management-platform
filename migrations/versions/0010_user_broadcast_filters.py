"""Sprint 2 — advanced segmentation: persist the segment filter on a user
broadcast and index participation_score for range filters.

filters (JSONB, nullable): the declarative SegmentFilter used for a custom
                           (advanced) broadcast. NULL for Sprint-1 quick
                           segments, whose meaning is carried by audience_type.

Index note: ix_users_participation_score supports the score min/max range
filter (the only numeric-range segment dimension). created_at, reservation
status, and the score-transaction columns are already indexed. country_id /
gender were left unindexed — add only if EXPLAIN on production volumes shows a
problematic sequential scan.

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-18 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("user_broadcasts", sa.Column("filters", JSONB, nullable=True))
    op.create_index(
        "ix_users_participation_score", "users", ["participation_score"]
    )


def downgrade() -> None:
    op.drop_index("ix_users_participation_score", table_name="users")
    op.drop_column("user_broadcasts", "filters")
