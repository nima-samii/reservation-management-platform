import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin


class ReservationSlot(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "reservation_slots"
    __table_args__ = (
        UniqueConstraint("slot_datetime", "channel_id", name="uq_slot_datetime_channel"),
    )

    slot_datetime: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    is_booked: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("channels.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    channel: Mapped["Channel"] = relationship("Channel", back_populates="slots")  # noqa: F821
    reservation: Mapped["Reservation | None"] = relationship(  # noqa: F821
        "Reservation", back_populates="slot", uselist=False
    )

    def __repr__(self) -> str:
        return f"<Slot {self.slot_datetime} ch={self.channel_id} booked={self.is_booked}>"
