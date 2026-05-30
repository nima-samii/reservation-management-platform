import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.channel import Channel
from app.db.models.reservation import Reservation, ReservationStatus
from app.db.models.slot import ReservationSlot
from app.repositories.base import BaseRepository


class ChannelRepository(BaseRepository[Channel]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Channel, session)

    async def get_all_channels(self) -> list[Channel]:
        stmt = select(Channel).order_by(Channel.priority.asc(), Channel.name.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_active_channels_ordered(self) -> list[Channel]:
        stmt = (
            select(Channel)
            .where(Channel.is_active == True)  # noqa: E712
            .order_by(Channel.priority.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_reservation_count_for_date(
        self, channel_id: uuid.UUID, slot_date: date
    ) -> int:
        """Count active reservations for a channel on a specific calendar date (UTC)."""
        stmt = (
            select(func.count(Reservation.id))
            .join(ReservationSlot, Reservation.slot_id == ReservationSlot.id)
            .where(
                Reservation.channel_id == channel_id,
                Reservation.status == ReservationStatus.ACTIVE,
                func.date(ReservationSlot.slot_datetime) == slot_date,
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar() or 0
