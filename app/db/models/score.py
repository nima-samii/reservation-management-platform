import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDMixin


class ScoreTransactionType(str, Enum):
    RESERVATION_REWARD = "reservation_reward"
    RESERVATION_CANCELLATION = "reservation_cancellation"
    NO_SHOW_PENALTY = "no_show_penalty"
    ADMIN_ADJUSTMENT = "admin_adjustment"
    # Score an admin entered when deciding whether a completed reservation was
    # attended. One type for both outcomes: the outcome does not determine the
    # sign (attending can be worth 0, an absence can still be worth points), so
    # splitting it in two would encode a rule that does not exist. Which
    # outcome it was lives in `reservations.attendance_status` and is mirrored
    # into this row's `meta`.
    ATTENDANCE_SCORE = "attendance_score"


class NotifyStatus(str, Enum):
    """Delivery state of the user-facing score-change notification."""

    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"


class ScoreTransaction(Base, UUIDMixin):
    """Immutable ledger row — one row per score event, never updated."""

    __tablename__ = "score_transactions"
    __table_args__ = (
        # These two carry explicit names because the migrations (0005) named them
        # differently from SQLAlchemy's column-level default. Declaring them here
        # keeps the ORM metadata in sync with the database, so a future
        # autogenerate won't try to drop-and-recreate them under new names.
        Index("ix_score_transactions_type", "transaction_type"),
        # Composite index backing paginated per-user score history (the common
        # access pattern); there is no standalone created_at index in the DB.
        Index("ix_score_transactions_user_created", "user_id", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reservation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("reservations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Indexed via ix_score_transactions_type in __table_args__ (see note there).
    transaction_type: Mapped[str] = mapped_column(String(40), nullable=False)
    score_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(256), nullable=True)
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Indexed via the composite ix_score_transactions_user_created (see
    # __table_args__); no standalone created_at index exists in the DB.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # ── Score-change notification delivery state ──────────────────────────
    # notify_status lifecycle: pending → sending → sent | failed | skipped.
    # notified_at is set on a terminal outcome and guards against double-sends.
    notify_status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="pending", index=True
    )
    notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped["User"] = relationship("User", back_populates="score_transactions")  # noqa: F821
    reservation: Mapped["Reservation | None"] = relationship("Reservation")  # noqa: F821

    def __repr__(self) -> str:
        return (
            f"<ScoreTransaction {self.transaction_type} "
            f"delta={self.score_delta:+d} user={self.user_id}>"
        )
