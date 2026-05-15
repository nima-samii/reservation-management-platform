from datetime import date, datetime, timedelta

import pytz
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models.slot import ReservationSlot
from app.repositories.slot import SlotRepository

logger = get_logger(__name__)

TZ = pytz.timezone(settings.TIMEZONE)


class SlotService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = SlotRepository(session)

    def _now_tz(self) -> datetime:
        return datetime.now(TZ)

    def _generate_slot_datetimes(self, for_date: date) -> list[datetime]:
        slots: list[datetime] = []
        start = TZ.localize(datetime(
            for_date.year, for_date.month, for_date.day,
            settings.SLOT_START_HOUR, 0, 0
        ))
        # Midnight = next day 00:00, so we use 24:00 equiv
        end_hour = settings.SLOT_END_HOUR
        if end_hour == 24:
            end = TZ.localize(datetime(
                for_date.year, for_date.month, for_date.day,
                23, 59, 59
            ))
        else:
            end = TZ.localize(datetime(
                for_date.year, for_date.month, for_date.day,
                end_hour, 0, 0
            ))

        current = start
        delta = timedelta(minutes=settings.SLOT_DURATION_MINUTES)
        while current < end:
            slots.append(current)
            current += delta
        return slots

    async def generate_slots_for_date(self, for_date: date) -> int:
        datetimes = self._generate_slot_datetimes(for_date)
        created = 0
        for dt in datetimes:
            if not await self._repo.slot_exists_for_datetime(dt):
                slot = ReservationSlot(slot_datetime=dt)
                await self._repo.save(slot)
                created += 1
        if created:
            logger.info("slots_generated", date=str(for_date), count=created)
        return created

    async def generate_slots_for_next_n_days(self, days: int) -> dict[str, int]:
        today = self._now_tz().date()
        results: dict[str, int] = {}
        for i in range(days):
            target = today + timedelta(days=i)
            count = await self.generate_slots_for_date(target)
            results[str(target)] = count
        return results

    async def get_available_slots_for_date(self, target_date: date) -> list[ReservationSlot]:
        now = self._now_tz()
        return await self._repo.get_available_slots_for_date(target_date, now)

    async def get_available_dates(self) -> list[date]:
        now = self._now_tz()
        to_dt = now + timedelta(days=settings.MAX_RESERVATION_DAYS_AHEAD)
        return await self._repo.get_dates_with_available_slots(now, to_dt)
