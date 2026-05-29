import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDMixin


class ScoreTransactionType(str, Enum):
    RESERVATION_REWARD = "reservation_reward"
    RESERVATION_CANCELLATION = "reservation_cancellation"
    NO_SHOW_PENALTY = "no_show_penalty"
    ADMIN_ADJUSTMENT = "admin_adjustment"


class ScoreTransaction(Base, UUIDMixin):
    """Immutable ledger row — one row per score event, never updated."""

    __tablename__ = "score_transactions"

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
    transaction_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    score_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(256), nullable=True)
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    user: Mapped["User"] = relationship("User", back_populates="score_transactions")  # noqa: F821
    reservation: Mapped["Reservation | None"] = relationship("Reservation")  # noqa: F821

    def __repr__(self) -> str:
        return (
            f"<ScoreTransaction {self.transaction_type} "
            f"delta={self.score_delta:+d} user={self.user_id}>"
        )
