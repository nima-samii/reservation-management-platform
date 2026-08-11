from sqlalchemy import BigInteger, Boolean, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin


class Channel(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "channels"
    __table_args__ = (
        UniqueConstraint("telegram_channel_id", name="uq_channels_telegram_id"),
    )

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    telegram_channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    invite_link: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # DEPRECATED — nothing reads this. It looks like a per-day booking limit and
    # is not one: a channel's real daily capacity is the number of slots
    # actually generated for it on that date, which is what both the unlock gate
    # (ThresholdUnlockStrategy) and the dashboard fill rate count. Trusting this
    # column instead was a live bug in both, fixed by counting rows.
    #
    # Kept rather than dropped because removing a NOT NULL column is a
    # destructive migration for a column that costs nothing to leave in place;
    # it is no longer exposed by any API or admin schema, so new code has no way
    # to pick it up by accident. SEQUENTIAL_FILL has no notion of capacity at
    # all — channels fill in priority order until their slots run out.
    capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    slots: Mapped[list["ReservationSlot"]] = relationship(  # noqa: F821
        "ReservationSlot", back_populates="channel"
    )
    reservations: Mapped[list["Reservation"]] = relationship(  # noqa: F821
        "Reservation", back_populates="channel"
    )

    def __repr__(self) -> str:
        return f"<Channel {self.name} (priority={self.priority})>"
