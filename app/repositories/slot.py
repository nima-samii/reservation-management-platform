import uuid
from datetime import date, datetime

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.slot import ReservationSlot
from app.repositories.base import BaseRepository


class SlotRepository(BaseRepository[ReservationSlot]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(ReservationSlot, session)

    def _day_bounds(self, target_date: date, tzinfo: object) -> tuple[datetime, datetime]:
        day_start = datetime(target_date.year, target_date.month, target_date.day, tzinfo=tzinfo)  # type: ignore[arg-type]
        day_end = datetime(target_date.year, target_date.month, target_date.day, 23, 59, 59, tzinfo=tzinfo)  # type: ignore[arg-type]
        return day_start, day_end

    async def get_available_slots_for_date_and_channel(
        self,
        target_date: date,
        channel_id: uuid.UUID,
        tz_now: datetime,
    ) -> list[ReservationSlot]:
        day_start, day_end = self._day_bounds(target_date, tz_now.tzinfo)
        stmt = (
            select(ReservationSlot)
            .where(
                and_(
                    ReservationSlot.slot_datetime >= day_start,
                    ReservationSlot.slot_datetime <= day_end,
                    ReservationSlot.is_booked == False,  # noqa: E712
                    ReservationSlot.slot_datetime > tz_now,
                    ReservationSlot.channel_id == channel_id,
                )
            )
            .order_by(ReservationSlot.slot_datetime.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_slots_for_date_and_channel(
        self, target_date: date, channel_id: uuid.UUID
    ) -> int:
        """Total slots generated for a channel on a calendar date.

        Uses the same ``func.date(slot_datetime) == target_date`` predicate as
        ChannelRepository.get_reservation_count_for_date so the two form a
        consistent fill ratio (booked / generated). This is the real per-day
        capacity — do NOT substitute the settings-derived _slots_per_day(),
        which diverges from the actual generated slots once the slot-schedule
        settings change after generation.
        """
        stmt = select(func.count(ReservationSlot.id)).where(
            func.date(ReservationSlot.slot_datetime) == target_date,
            ReservationSlot.channel_id == channel_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def get_slot_with_lock(self, slot_id: uuid.UUID) -> ReservationSlot | None:
        stmt = (
            select(ReservationSlot)
            .where(ReservationSlot.id == slot_id)
            .with_for_update(nowait=True)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def slot_exists_for_datetime_and_channel(
        self, dt: datetime, channel_id: uuid.UUID
    ) -> bool:
        stmt = (
            select(ReservationSlot.id)
            .where(
                ReservationSlot.slot_datetime == dt,
                ReservationSlot.channel_id == channel_id,
            )
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar() is not None

    async def get_dates_with_available_slots(
        self, from_dt: datetime, to_dt: datetime
    ) -> list[date]:
        stmt = (
            select(func.date(ReservationSlot.slot_datetime))
            .where(
                and_(
                    ReservationSlot.slot_datetime >= from_dt,
                    ReservationSlot.slot_datetime <= to_dt,
                    ReservationSlot.is_booked == False,  # noqa: E712
                    ReservationSlot.slot_datetime > from_dt,
                )
            )
            .group_by(func.date(ReservationSlot.slot_datetime))
            .order_by(func.date(ReservationSlot.slot_datetime).asc())
        )
        result = await self.session.execute(stmt)
        return [row[0] for row in result.all()]
