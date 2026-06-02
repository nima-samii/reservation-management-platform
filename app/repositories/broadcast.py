import uuid
from datetime import date
from math import ceil

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.broadcast_log import BroadcastLog, BroadcastStatus
from app.db.models.channel import Channel
from app.db.models.schedule_event import ScheduleEvent
from app.repositories.base import BaseRepository


class BroadcastRepository(BaseRepository[BroadcastLog]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(BroadcastLog, session)

    async def get_for_channel_and_date(
        self, channel_id: uuid.UUID, broadcast_date: date
    ) -> BroadcastLog | None:
        stmt = select(BroadcastLog).where(
            BroadcastLog.channel_id == channel_id,
            BroadcastLog.broadcast_date == broadcast_date,
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_previous_sent(
        self, channel_id: uuid.UUID, before_date: date
    ) -> BroadcastLog | None:
        """Return the most recent successfully sent broadcast before before_date."""
        stmt = (
            select(BroadcastLog)
            .where(
                BroadcastLog.channel_id == channel_id,
                BroadcastLog.status == BroadcastStatus.SENT.value,
                BroadcastLog.broadcast_date < before_date,
                BroadcastLog.telegram_message_id.is_not(None),
            )
            .order_by(BroadcastLog.broadcast_date.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def log_success(
        self,
        channel_id: uuid.UUID,
        telegram_message_id: int,
        broadcast_date: date,
    ) -> BroadcastLog:
        entry = BroadcastLog(
            channel_id=channel_id,
            telegram_message_id=telegram_message_id,
            broadcast_date=broadcast_date,
            status=BroadcastStatus.SENT.value,
        )
        return await self.save(entry)

    async def log_failure(
        self,
        channel_id: uuid.UUID,
        broadcast_date: date,
        error_message: str,
    ) -> BroadcastLog:
        entry = BroadcastLog(
            channel_id=channel_id,
            telegram_message_id=None,
            broadcast_date=broadcast_date,
            status=BroadcastStatus.FAILED.value,
            error_message=error_message,
        )
        return await self.save(entry)


    async def admin_list(
        self,
        *,
        broadcast_date: date | None = None,
        channel_id: uuid.UUID | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[dict], int]:
        """Return paginated broadcast logs with channel name included."""
        filters = []
        if broadcast_date is not None:
            filters.append(BroadcastLog.broadcast_date == broadcast_date)
        if channel_id is not None:
            filters.append(BroadcastLog.channel_id == channel_id)

        count_stmt = select(func.count(BroadcastLog.id))
        if filters:
            count_stmt = count_stmt.where(*filters)
        total = (await self.session.execute(count_stmt)).scalar() or 0

        stmt = (
            select(BroadcastLog, Channel.name.label("channel_name"))
            .outerjoin(Channel, BroadcastLog.channel_id == Channel.id)
            .order_by(BroadcastLog.sent_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        if filters:
            stmt = stmt.where(*filters)
        rows = (await self.session.execute(stmt)).all()
        items = [
            {
                "id": str(row.BroadcastLog.id),
                "channel_id": str(row.BroadcastLog.channel_id) if row.BroadcastLog.channel_id else None,
                "channel_name": row.channel_name,
                "broadcast_date": row.BroadcastLog.broadcast_date.isoformat(),
                "status": row.BroadcastLog.status,
                "telegram_message_id": row.BroadcastLog.telegram_message_id,
                "error_message": row.BroadcastLog.error_message,
                "sent_at": row.BroadcastLog.sent_at.isoformat(),
            }
            for row in rows
        ]
        return items, total


class ScheduleEventRepository(BaseRepository[ScheduleEvent]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(ScheduleEvent, session)

    async def get_for_date_and_channel(
        self, channel_id: uuid.UUID, target_date: date
    ) -> list[ScheduleEvent]:
        """Return active events for the given date that apply to this channel
        (channel-specific events + global events where channel_id IS NULL),
        ordered by sort_order."""
        stmt = (
            select(ScheduleEvent)
            .where(
                ScheduleEvent.event_date == target_date,
                ScheduleEvent.is_active.is_(True),
                (ScheduleEvent.channel_id == channel_id)
                | ScheduleEvent.channel_id.is_(None),
            )
            .order_by(ScheduleEvent.sort_order.asc(), ScheduleEvent.title.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_events_in_range(
        self,
        date_from: date,
        date_to: date,
        channel_id: uuid.UUID | None = None,
    ) -> list[ScheduleEvent]:
        filters = [
            ScheduleEvent.event_date >= date_from,
            ScheduleEvent.event_date <= date_to,
            ScheduleEvent.is_active.is_(True),
        ]
        if channel_id is not None:
            filters.append(ScheduleEvent.channel_id == channel_id)
        stmt = (
            select(ScheduleEvent)
            .where(*filters)
            .options(selectinload(ScheduleEvent.channel))
            .order_by(ScheduleEvent.event_date.asc(), ScheduleEvent.sort_order.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
