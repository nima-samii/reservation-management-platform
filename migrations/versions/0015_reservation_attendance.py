"""Reservation attendance & manual scoring — attendance decision columns.

reservations: + attendance_status, attendance_score_delta, attendance_reason,
attendance_marked_by, attendance_marked_at.

Records the admin's post-session decision about a completed reservation. The
outcome (`attendance_status`: 'attended' | 'absent') and the score
(`attendance_score_delta`) are independent by design — every combination is
legal, including a score of 0 and a positive score on an absence.

All five columns are nullable and written together by a single conditional
UPDATE guarded on `attendance_status IS NULL`, which is what makes each
completed reservation decidable exactly once. NULL therefore means "no decision
yet", which is also the correct reading for every pre-existing row.

Deliberately **no backfill** of the legacy no-show flag
(`notes->>'no_show_penalty_applied'`) into `attendance_status`. That flag is
still read by the dashboard counters, the reservation summaries and broadcast
segmentation, and reconciling the two histories is Phase 7's decision, not a
side effect of adding columns. Until then, old no-shows are recorded only where
they always were, and appear here as undecided.

`ix_reservations_attendance_status` is plain rather than partial: it has to
serve `IS NULL` (the admin's "awaiting a decision" queue) as well as equality
on a decided value, and Postgres indexes NULLs.

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-03 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "reservations",
        sa.Column("attendance_status", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "reservations",
        sa.Column("attendance_score_delta", sa.Integer(), nullable=True),
    )
    op.add_column(
        "reservations",
        sa.Column("attendance_reason", sa.String(length=256), nullable=True),
    )
    op.add_column(
        "reservations",
        sa.Column("attendance_marked_by", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "reservations",
        sa.Column(
            "attendance_marked_at", sa.DateTime(timezone=True), nullable=True
        ),
    )

    op.create_index(
        "ix_reservations_attendance_status",
        "reservations",
        ["attendance_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_reservations_attendance_status", table_name="reservations")
    op.drop_column("reservations", "attendance_marked_at")
    op.drop_column("reservations", "attendance_marked_by")
    op.drop_column("reservations", "attendance_reason")
    op.drop_column("reservations", "attendance_score_delta")
    op.drop_column("reservations", "attendance_status")
