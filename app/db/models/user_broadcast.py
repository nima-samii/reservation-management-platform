import uuid
from datetime import datetime
from enum import Enum

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin


class UserBroadcastStatus(str, Enum):
    DRAFT = "draft"
    PENDING = "pending"
    SCHEDULED = "scheduled"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class UserBroadcastAudience(str, Enum):
    ALL_USERS = "all_users"
    ACTIVE_USERS = "active_users"
    USERS_WITH_RESERVATIONS = "users_with_reservations"


class RecipientStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    BLOCKED = "blocked"


class MediaType(str, Enum):
    TEXT = "text"
    PHOTO = "photo"
    DOCUMENT = "document"


class RecurrenceFrequency(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class UserBroadcast(Base, UUIDMixin):
    """One direct-message broadcast to a resolved user audience.

    The row is created in PENDING state, its recipient set is snapshotted into
    user_broadcast_recipients, then a background job transitions it through
    PROCESSING → COMPLETED (or FAILED). The success/failed/blocked counters are
    persisted periodically so the progress endpoint reflects live state.
    """

    __tablename__ = "user_broadcasts"

    message: Mapped[str] = mapped_column(sa.Text, nullable=False)
    parse_mode: Mapped[str] = mapped_column(sa.String(10), nullable=False, server_default="HTML")
    audience_type: Mapped[str] = mapped_column(sa.String(40), nullable=False, index=True)
    # Declarative SegmentFilter for advanced (audience_type="custom") broadcasts;
    # NULL for Sprint-1 quick segments. Retained for analytics / future reuse.
    # Sprint 3: persisted for scheduled/recurring/draft so the audience can be
    # re-resolved at execution time.
    filters: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(
        sa.String(20), nullable=False, server_default=UserBroadcastStatus.PENDING.value, index=True
    )

    # ── Sprint 3: media ─────────────────────────────────────────────────────
    media_type: Mapped[str] = mapped_column(
        sa.String(20), nullable=False, server_default=MediaType.TEXT.value
    )
    # Telegram file_id (NOT binary). For photo/document; NULL for text.
    media_file_id: Mapped[str | None] = mapped_column(sa.String(256), nullable=True)

    # ── Sprint 3: scheduling / templates ────────────────────────────────────
    scheduled_for: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True, index=True
    )
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("broadcast_templates.id", ondelete="SET NULL"),
        nullable=True,
    )

    total_recipients: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default="0")
    success_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default="0")
    failed_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default="0")
    blocked_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default="0")

    created_by: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False, index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)

    recipients: Mapped[list["UserBroadcastRecipient"]] = relationship(
        "UserBroadcastRecipient",
        back_populates="broadcast",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<UserBroadcast {self.audience_type} status={self.status} "
            f"total={self.total_recipients}>"
        )


class UserBroadcastRecipient(Base, UUIDMixin):
    """Per-user delivery row for a UserBroadcast — fills the per-recipient
    tracking gap the channel broadcast_logs table does not cover."""

    __tablename__ = "user_broadcast_recipients"
    __table_args__ = (
        sa.Index("ix_user_broadcast_recipients_broadcast_status", "broadcast_id", "status"),
    )

    broadcast_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("user_broadcasts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    telegram_id: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(
        sa.String(10), nullable=False, server_default=RecipientStatus.PENDING.value
    )
    error_message: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)

    broadcast: Mapped["UserBroadcast"] = relationship(
        "UserBroadcast", back_populates="recipients"
    )

    def __repr__(self) -> str:
        return (
            f"<UserBroadcastRecipient broadcast={self.broadcast_id} "
            f"tg={self.telegram_id} status={self.status}>"
        )


class BroadcastTemplate(Base, UUIDMixin, TimestampMixin):
    """Reusable message template (text + optional media). Holds content only —
    no audience or schedule. Used to prefill a broadcast at creation time."""

    __tablename__ = "broadcast_templates"

    name: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(sa.String(512), nullable=True)
    message: Mapped[str] = mapped_column(sa.Text, nullable=False)
    parse_mode: Mapped[str] = mapped_column(sa.String(10), nullable=False, server_default="HTML")
    media_type: Mapped[str] = mapped_column(
        sa.String(20), nullable=False, server_default=MediaType.TEXT.value
    )
    media_file_id: Mapped[str | None] = mapped_column(sa.String(256), nullable=True)

    def __repr__(self) -> str:
        return f"<BroadcastTemplate {self.name}>"


class BroadcastRecurringRule(Base, UUIDMixin):
    """Recurrence definition attached to a source (draft) broadcast. Each fire
    creates a NEW UserBroadcast run — historical runs are never overwritten."""

    __tablename__ = "broadcast_recurring_rules"

    broadcast_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("user_broadcasts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    frequency: Mapped[str] = mapped_column(sa.String(20), nullable=False)
    interval: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default="1")
    # weekly: 0=Monday .. 6=Sunday; monthly: 1..31; NULL when not applicable.
    day_of_week: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    day_of_month: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    next_run_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, index=True
    )
    is_active: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default="true", index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<BroadcastRecurringRule {self.frequency} every {self.interval} "
            f"next={self.next_run_at} active={self.is_active}>"
        )
