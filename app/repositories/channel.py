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

    async def get_max_priority(self) -> int:
        stmt = select(func.max(Channel.priority))
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def get_neighbor(self, channel: Channel, direction: str) -> Channel | None:
        """The adjacent channel in priority order, for move-up/down reordering."""
        stmt = select(Channel).order_by(
            Channel.priority.desc() if direction == "up" else Channel.priority.asc()
        )
        if direction == "up":
            stmt = stmt.where(Channel.priority < channel.priority)
        else:
            stmt = stmt.where(Channel.priority > channel.priority)
        result = await self.session.execute(stmt.limit(1))
        return result.scalars().first()

    async def has_any_slots_or_reservations(self, channel_id: uuid.UUID) -> bool:
        """Whether any reservation_slots or reservations row references this
        channel (past or future) — mirrors the ON DELETE RESTRICT FK so the
        API can reject with a clean 422 instead of a raw IntegrityError."""
        slot_stmt = select(func.count(ReservationSlot.id)).where(
            ReservationSlot.channel_id == channel_id
        )
        reservation_stmt = select(func.count(Reservation.id)).where(
            Reservation.channel_id == channel_id
        )
        slot_count = (await self.session.execute(slot_stmt)).scalar() or 0
        if slot_count:
            return True
        reservation_count = (await self.session.execute(reservation_stmt)).scalar() or 0
        return bool(reservation_count)

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
