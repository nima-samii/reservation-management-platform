"""Add user broadcast support: bot_blocked flag + user_broadcasts and
user_broadcast_recipients tables.

bot_blocked:                 marks users who blocked the bot so they are
                             excluded from future broadcast audiences.
user_broadcasts:             one row per direct-message broadcast to a user
                             audience, with aggregate delivery counters.
user_broadcast_recipients:   per-user delivery tracking (status + error).

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-18 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── users.bot_blocked ─────────────────────────────────────────────────────
    op.add_column(
        "users",
        sa.Column("bot_blocked", sa.Boolean(), nullable=False, server_default="false"),
    )

    # ── user_broadcasts ───────────────────────────────────────────────────────
    op.create_table(
        "user_broadcasts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("parse_mode", sa.String(10), nullable=False, server_default="HTML"),
        sa.Column("audience_type", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("total_recipients", sa.Integer, nullable=False, server_default="0"),
        sa.Column("success_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("blocked_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_user_broadcasts_audience_type", "user_broadcasts", ["audience_type"])
    op.create_index("ix_user_broadcasts_status", "user_broadcasts", ["status"])
    op.create_index("ix_user_broadcasts_created_at", "user_broadcasts", ["created_at"])

    # ── user_broadcast_recipients ─────────────────────────────────────────────
    op.create_table(
        "user_broadcast_recipients",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "broadcast_id",
            UUID(as_uuid=True),
            sa.ForeignKey("user_broadcasts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("telegram_id", sa.BigInteger, nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_user_broadcast_recipients_broadcast_id", "user_broadcast_recipients", ["broadcast_id"])
    op.create_index("ix_user_broadcast_recipients_user_id", "user_broadcast_recipients", ["user_id"])
    op.create_index(
        "ix_user_broadcast_recipients_broadcast_status",
        "user_broadcast_recipients",
        ["broadcast_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_user_broadcast_recipients_broadcast_status", table_name="user_broadcast_recipients")
    op.drop_index("ix_user_broadcast_recipients_user_id", table_name="user_broadcast_recipients")
    op.drop_index("ix_user_broadcast_recipients_broadcast_id", table_name="user_broadcast_recipients")
    op.drop_table("user_broadcast_recipients")

    op.drop_index("ix_user_broadcasts_created_at", table_name="user_broadcasts")
    op.drop_index("ix_user_broadcasts_status", table_name="user_broadcasts")
    op.drop_index("ix_user_broadcasts_audience_type", table_name="user_broadcasts")
    op.drop_table("user_broadcasts")

    op.drop_column("users", "bot_blocked")
