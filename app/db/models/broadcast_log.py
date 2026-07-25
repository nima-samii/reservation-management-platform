import uuid
from datetime import date, datetime
from enum import Enum

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDMixin


class BroadcastStatus(str, Enum):
    SENT = "sent"
    FAILED = "failed"


class BroadcastLog(Base, UUIDMixin):
    """Tracks one broadcast per channel per calendar day.

    Unique constraint on (channel_id, broadcast_date) prevents duplicate
    broadcasts. telegram_message_id enables future pin/edit/delete operations.
    """

    __tablename__ = "broadcast_logs"
    __table_args__ = (
        sa.UniqueConstraint(
            "channel_id",
            "broadcast_date",
            name="uq_broadcast_logs_channel_date",
        ),
    )

    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("channels.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    telegram_message_id: Mapped[int | None] = mapped_column(
        sa.BigInteger, nullable=True
    )
    broadcast_date: Mapped[date] = mapped_column(sa.Date, nullable=False, index=True)
    sent_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.text("NOW()"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(sa.String(10), nullable=False)
    error_message: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<BroadcastLog channel={self.channel_id} "
            f"date={self.broadcast_date} status={self.status}>"
        )
