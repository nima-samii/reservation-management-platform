import uuid
from datetime import datetime
from enum import Enum

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDMixin


class ReminderType(str, Enum):
    SAME_DAY = "same_day"
    PRE_SESSION = "pre_session"


class DeliveryStatus(str, Enum):
    SENT = "sent"
    FAILED = "failed"


class NotificationLog(Base, UUIDMixin):
    __tablename__ = "notification_logs"
    __table_args__ = (
        sa.UniqueConstraint(
            "reservation_id",
            "reminder_type",
            name="uq_notification_log_reservation_type",
        ),
    )

    reservation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("reservations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reminder_type: Mapped[str] = mapped_column(sa.String(20), nullable=False)
    status: Mapped[str] = mapped_column(sa.String(10), nullable=False)
    error_message: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.text("NOW()"),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<NotificationLog res={self.reservation_id} type={self.reminder_type} status={self.status}>"
