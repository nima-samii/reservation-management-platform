import uuid
from datetime import date

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDMixin


class ScheduleEvent(Base, UUIDMixin):
    """Admin-configurable event blocks injected into daily broadcast schedules.

    channel_id=NULL means the event appears in every channel's broadcast.
    """

    __tablename__ = "schedule_events"

    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("channels.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    event_date: Mapped[date] = mapped_column(sa.Date, nullable=False, index=True)
    title: Mapped[str] = mapped_column(sa.String(256), nullable=False)
    sort_order: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)

    channel: Mapped["Channel | None"] = relationship("Channel")  # noqa: F821

    def __repr__(self) -> str:
        return f"<ScheduleEvent date={self.event_date} title={self.title!r}>"
