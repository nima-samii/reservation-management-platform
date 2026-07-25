import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin


class Gender(str, Enum):
    MALE = "male"
    FEMALE = "female"
    NOT_SAY = "not_say"


class User(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("telegram_id", name="uq_users_telegram_id"),
        UniqueConstraint("public_user_code", name="uq_users_public_code"),
    )

    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    public_user_code: Mapped[str] = mapped_column(String(6), nullable=False)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    full_name: Mapped[str] = mapped_column(String(256), nullable=False)
    gender: Mapped[str | None] = mapped_column(String(10), nullable=True)
    country_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("countries.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Set to True when a broadcast/notification send raises TelegramForbiddenError
    # (user blocked the bot or deleted their account). Such users are excluded
    # from every future broadcast audience.
    bot_blocked: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )
    # Indexed (migration 0010) to back the score min/max range segment filter.
    participation_score: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, server_default="0", index=True
    )
    # Refreshed to now() on every successful reservation create (never on
    # cancellation) — the reset anchor for the inactivity-reminder cycle.
    last_reservation_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    # Last time an inactivity reminder was delivered to this user.
    last_inactivity_reminder_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    country_rel: Mapped["Country"] = relationship("Country", back_populates="users")  # noqa: F821
    reservations: Mapped[list["Reservation"]] = relationship(  # noqa: F821
        "Reservation", back_populates="user", cascade="all, delete-orphan"
    )
    audit_logs: Mapped[list["AuditLog"]] = relationship(  # noqa: F821
        "AuditLog", back_populates="user"
    )
    score_transactions: Mapped[list["ScoreTransaction"]] = relationship(  # noqa: F821
        "ScoreTransaction", back_populates="user"
    )

    def __repr__(self) -> str:
        return f"<User {self.public_user_code}: {self.full_name}>"
