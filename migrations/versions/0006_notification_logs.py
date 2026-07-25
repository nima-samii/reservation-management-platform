"""Add notification_logs table for reminder deduplication and delivery tracking.

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-23 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notification_logs",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "reservation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("reservations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reminder_type", sa.String(20), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )

    op.create_index("ix_notification_logs_reservation_id", "notification_logs", ["reservation_id"])

    # Unique per (reservation, reminder_type) — core deduplication guarantee
    op.create_unique_constraint(
        "uq_notification_log_reservation_type",
        "notification_logs",
        ["reservation_id", "reminder_type"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_notification_log_reservation_type", "notification_logs", type_="unique")
    op.drop_index("ix_notification_logs_reservation_id", table_name="notification_logs")
    op.drop_table("notification_logs")
