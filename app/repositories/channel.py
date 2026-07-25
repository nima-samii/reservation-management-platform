import uuid
from datetime import date

from sqlalchemy import delete as sa_delete
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

    async def count_active_reservations(self, channel_id: uuid.UUID) -> int:
        """Number of ACTIVE reservations referencing this channel. Cancelled,
        completed and expired rows don't count — they're safe to remove."""
        stmt = select(func.count(Reservation.id)).where(
            Reservation.channel_id == channel_id,
            Reservation.status == ReservationStatus.ACTIVE,
        )
        return (await self.session.execute(stmt)).scalar() or 0

    async def delete_with_slots_and_reservations(self, channel: Channel) -> None:
        """Hard-delete the channel together with all its reservation_slots and
        its non-active reservations.

        The caller MUST have verified there are no ACTIVE reservations first
        (see :meth:`count_active_reservations`). Order matters because both
        reservations→slots and slots/reservations→channel use ON DELETE RESTRICT:
        remove reservations, then slots, then the channel itself.
        """
        await self.session.execute(
            sa_delete(Reservation).where(Reservation.channel_id == channel.id)
        )
        await self.session.execute(
            sa_delete(ReservationSlot).where(ReservationSlot.channel_id == channel.id)
        )
        await self.session.delete(channel)
        await self.session.flush()

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
