"""Add broadcast_logs and schedule_events tables.

broadcast_logs: tracks per-channel daily broadcast with telegram_message_id
                for pin/edit/delete and audit trail.
schedule_events: admin-configurable event blocks injected into daily schedules.

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-29 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── schedule_events ───────────────────────────────────────────────────────
    op.create_table(
        "schedule_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("channel_id", UUID(as_uuid=True), sa.ForeignKey("channels.id", ondelete="SET NULL"), nullable=True),
        sa.Column("event_date", sa.Date, nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
    )
    op.create_index("ix_schedule_events_date", "schedule_events", ["event_date"])
    op.create_index("ix_schedule_events_channel_id", "schedule_events", ["channel_id"])

    # ── broadcast_logs ────────────────────────────────────────────────────────
    op.create_table(
        "broadcast_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("channel_id", UUID(as_uuid=True), sa.ForeignKey("channels.id", ondelete="SET NULL"), nullable=True),
        sa.Column("telegram_message_id", sa.BigInteger, nullable=True),
        sa.Column("broadcast_date", sa.Date, nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("error_message", sa.Text, nullable=True),
    )
    op.create_index("ix_broadcast_logs_channel_id", "broadcast_logs", ["channel_id"])
    op.create_index("ix_broadcast_logs_broadcast_date", "broadcast_logs", ["broadcast_date"])
    op.create_unique_constraint(
        "uq_broadcast_logs_channel_date",
        "broadcast_logs",
        ["channel_id", "broadcast_date"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_broadcast_logs_channel_date", "broadcast_logs", type_="unique")
    op.drop_index("ix_broadcast_logs_broadcast_date", table_name="broadcast_logs")
    op.drop_index("ix_broadcast_logs_channel_id", table_name="broadcast_logs")
    op.drop_table("broadcast_logs")

    op.drop_index("ix_schedule_events_channel_id", table_name="schedule_events")
    op.drop_index("ix_schedule_events_date", table_name="schedule_events")
    op.drop_table("schedule_events")
