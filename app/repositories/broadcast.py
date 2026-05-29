import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.broadcast_log import BroadcastLog, BroadcastStatus
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
