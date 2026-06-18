import uuid
from datetime import datetime
from enum import Enum

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDMixin


class UserBroadcastStatus(str, Enum):
    PENDING = "pending"
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
    filters: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(
        sa.String(20), nullable=False, server_default=UserBroadcastStatus.PENDING.value, index=True
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
