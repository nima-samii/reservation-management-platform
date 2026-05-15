from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.channel import Channel
from app.db.models.reservation import Reservation, ReservationStatus
from app.repositories.base import BaseRepository


class ChannelRepository(BaseRepository[Channel]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Channel, session)

    async def get_active_channels_ordered(self) -> list[Channel]:
        stmt = (
            select(Channel)
            .where(Channel.is_active == True)  # noqa: E712
            .order_by(Channel.priority.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_reservation_count(self, channel: Channel) -> int:
        stmt = select(func.count(Reservation.id)).where(
            Reservation.channel_id == channel.id,
            Reservation.status == ReservationStatus.ACTIVE,
        )
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def get_assignable_channel(self, threshold: float) -> Channel | None:
        channels = await self.get_active_channels_ordered()
        for channel in channels:
            count = await self.get_reservation_count(channel)
            fill_ratio = count / channel.capacity if channel.capacity > 0 else 1.0
            if fill_ratio < threshold:
                return channel
        return None
