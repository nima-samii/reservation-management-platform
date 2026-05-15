import uuid
from enum import Enum

from sqlalchemy import ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin


class ReservationStatus(str, Enum):
    ACTIVE = "active"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    NO_SHOW = "no_show"


class Reservation(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "reservations"
    __table_args__ = (
        # Partial unique index: only one ACTIVE reservation per slot.
        # Cancelled/completed rows don't block re-booking the same slot.
        Index(
            "uq_reservations_slot_active",
            "slot_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    slot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("reservation_slots.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("channels.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default=ReservationStatus.ACTIVE,
        nullable=False,
        index=True,
    )
    notes: Mapped[str | None] = mapped_column(String(512), nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="reservations")  # noqa: F821
    slot: Mapped["ReservationSlot"] = relationship(  # noqa: F821
        "ReservationSlot", back_populates="reservation"
    )
    channel: Mapped["Channel"] = relationship("Channel", back_populates="reservations")  # noqa: F821

    def __repr__(self) -> str:
        return f"<Reservation {self.id} status={self.status}>"
