"""Sprint 3 — marketing automation foundation: drafts, templates, media,
scheduled + recurring broadcasts.

user_broadcasts:            + media_type, media_file_id, scheduled_for, template_id.
                            status now also accepts 'draft' / 'scheduled'
                            (no DB enum — status is a String column).
broadcast_templates:        reusable message+media content for prefilling.
broadcast_recurring_rules:  recurrence definition attached to a source draft;
                            each fire creates a new run (history is append-only).

Index notes: user_broadcasts.scheduled_for (due-schedule lookups);
broadcast_recurring_rules(next_run_at) and (is_active) for the recurring
dispatcher's due-rule query. No new index on user_broadcasts.status (already
indexed since 0009).

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-18 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── broadcast_templates (created first; referenced by user_broadcasts FK) ──
    op.create_table(
        "broadcast_templates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.String(512), nullable=True),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("parse_mode", sa.String(10), nullable=False, server_default="HTML"),
        sa.Column("media_type", sa.String(20), nullable=False, server_default="text"),
        sa.Column("media_file_id", sa.String(256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
    )

    # ── user_broadcasts new columns ────────────────────────────────────────────
    op.add_column("user_broadcasts", sa.Column("media_type", sa.String(20), nullable=False, server_default="text"))
    op.add_column("user_broadcasts", sa.Column("media_file_id", sa.String(256), nullable=True))
    op.add_column("user_broadcasts", sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True))
    op.add_column("user_broadcasts", sa.Column("template_id", UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_user_broadcasts_template_id",
        "user_broadcasts",
        "broadcast_templates",
        ["template_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_user_broadcasts_scheduled_for", "user_broadcasts", ["scheduled_for"])

    # ── broadcast_recurring_rules ──────────────────────────────────────────────
    op.create_table(
        "broadcast_recurring_rules",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "broadcast_id",
            UUID(as_uuid=True),
            sa.ForeignKey("user_broadcasts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("frequency", sa.String(20), nullable=False),
        sa.Column("interval", sa.Integer, nullable=False, server_default="1"),
        sa.Column("day_of_week", sa.Integer, nullable=True),
        sa.Column("day_of_month", sa.Integer, nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
    )
    op.create_index("ix_broadcast_recurring_rules_broadcast_id", "broadcast_recurring_rules", ["broadcast_id"])
    op.create_index("ix_broadcast_recurring_rules_next_run_at", "broadcast_recurring_rules", ["next_run_at"])
    op.create_index("ix_broadcast_recurring_rules_is_active", "broadcast_recurring_rules", ["is_active"])


def downgrade() -> None:
    op.drop_index("ix_broadcast_recurring_rules_is_active", table_name="broadcast_recurring_rules")
    op.drop_index("ix_broadcast_recurring_rules_next_run_at", table_name="broadcast_recurring_rules")
    op.drop_index("ix_broadcast_recurring_rules_broadcast_id", table_name="broadcast_recurring_rules")
    op.drop_table("broadcast_recurring_rules")

    op.drop_index("ix_user_broadcasts_scheduled_for", table_name="user_broadcasts")
    op.drop_constraint("fk_user_broadcasts_template_id", "user_broadcasts", type_="foreignkey")
    op.drop_column("user_broadcasts", "template_id")
    op.drop_column("user_broadcasts", "scheduled_for")
    op.drop_column("user_broadcasts", "media_file_id")
    op.drop_column("user_broadcasts", "media_type")

    op.drop_table("broadcast_templates")
