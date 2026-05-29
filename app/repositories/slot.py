from datetime import date, datetime

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.slot import ReservationSlot
from app.repositories.base import BaseRepository


class SlotRepository(BaseRepository[ReservationSlot]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(ReservationSlot, session)

    async def get_available_slots_for_date(
        self, target_date: date, tz_now: datetime
    ) -> list[ReservationSlot]:
        day_start = datetime(
            target_date.year, target_date.month, target_date.day,
            tzinfo=tz_now.tzinfo
        )
        day_end = datetime(
            target_date.year, target_date.month, target_date.day,
            23, 59, 59, tzinfo=tz_now.tzinfo
        )
        stmt = (
            select(ReservationSlot)
            .where(
                and_(
                    ReservationSlot.slot_datetime >= day_start,
                    ReservationSlot.slot_datetime <= day_end,
                    ReservationSlot.is_booked == False,  # noqa: E712
                    ReservationSlot.slot_datetime > tz_now,
                )
            )
            .order_by(ReservationSlot.slot_datetime.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_slot_with_lock(self, slot_id: str) -> ReservationSlot | None:
        stmt = (
            select(ReservationSlot)
            .where(ReservationSlot.id == slot_id)
            .with_for_update(nowait=True)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def slot_exists_for_datetime(self, dt: datetime) -> bool:
        stmt = select(ReservationSlot.id).where(
            ReservationSlot.slot_datetime == dt
        ).limit(1)
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
