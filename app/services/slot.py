from datetime import date, datetime, timedelta
from typing import TypedDict

import pytz
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.booking_rules import is_same_day_cutoff_passed
from app.core.config import settings
from app.core.logging import get_logger
from app.db.models.slot import ReservationSlot
from app.repositories.channel import ChannelRepository
from app.repositories.slot import SlotRepository

logger = get_logger(__name__)

TZ = pytz.timezone(settings.TIMEZONE)


class GroupedSlots(TypedDict):
    recommended: list[ReservationSlot]
    more_available: list[ReservationSlot]


class SlotService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = SlotRepository(session)
        self._channel_repo = ChannelRepository(session)

    def _now_tz(self) -> datetime:
        return datetime.now(TZ)

    def _slots_per_day(self) -> int:
        count = int(
            (settings.SLOT_END_HOUR - settings.SLOT_START_HOUR) * 60
            / settings.SLOT_DURATION_MINUTES
        )
        if settings.ENABLE_FINAL_MIDNIGHT_SLOT:
            count += 1
        return count

    def _parse_final_slot_time(self) -> tuple[int, int]:
        """Parse FINAL_SLOT_TIME ('HH:MM') into (hour, minute)."""
        parts = settings.FINAL_SLOT_TIME.split(":")
        return int(parts[0]), int(parts[1])

    def _generate_slot_datetimes(self, for_date: date) -> list[datetime]:
        slots: list[datetime] = []
        start = TZ.localize(datetime(
            for_date.year, for_date.month, for_date.day,
            settings.SLOT_START_HOUR, 0, 0,
        ))
        end_hour = settings.SLOT_END_HOUR
        if end_hour == 24:
            end = TZ.localize(datetime(for_date.year, for_date.month, for_date.day, 23, 59, 59))
        else:
            end = TZ.localize(datetime(for_date.year, for_date.month, for_date.day, end_hour, 0, 0))

        current = start
        delta = timedelta(minutes=settings.SLOT_DURATION_MINUTES)
        while current < end:
            slots.append(current)
            current += delta

        if settings.ENABLE_FINAL_MIDNIGHT_SLOT:
            fh, fm = self._parse_final_slot_time()
            final = TZ.localize(datetime(for_date.year, for_date.month, for_date.day, fh, fm, 0))
            if final not in slots:
                slots.append(final)

        return slots

    async def generate_slots_for_date(self, for_date: date) -> int:
        channels = await self._channel_repo.get_active_channels_ordered()
        datetimes = self._generate_slot_datetimes(for_date)
        created = 0
        for channel in channels:
            for dt in datetimes:
                if not await self._repo.slot_exists_for_datetime_and_channel(dt, channel.id):
                    slot = ReservationSlot(slot_datetime=dt, channel_id=channel.id)
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

    async def get_available_slots_for_date_grouped(self, slot_date: date) -> GroupedSlots:
        """
        Returns slots grouped into two sections:
        - recommended: Channel 1 (always open) available slots
        - more_available: Channel 2+ slots, unlocked when the preceding channel
          reaches CHANNEL_CAPACITY_THRESHOLD fill ratio for that day

        Returns empty groups when the same-day cutoff has passed for today.
        """
        threshold = settings.CHANNEL_CAPACITY_THRESHOLD
        slots_per_day = self._slots_per_day()
        now = self._now_tz()

        if is_same_day_cutoff_passed(slot_date, now, settings.SAME_DAY_CUTOFF_HOUR):
            return GroupedSlots(recommended=[], more_available=[])
        channels = await self._channel_repo.get_active_channels_ordered()

        recommended: list[ReservationSlot] = []
        more_available: list[ReservationSlot] = []
        next_channel_unlocked = False

        for i, channel in enumerate(channels):
            if i > 0 and not next_channel_unlocked:
                break

            slots = await self._repo.get_available_slots_for_date_and_channel(
                slot_date, channel.id, now
            )
            booked = await self._channel_repo.get_reservation_count_for_date(
                channel.id, slot_date
            )
            fill_ratio = booked / slots_per_day if slots_per_day > 0 else 1.0
            next_channel_unlocked = fill_ratio >= threshold

            if i == 0:
                recommended.extend(slots)
            else:
                more_available.extend(slots)

        return GroupedSlots(recommended=recommended, more_available=more_available)

    async def get_available_dates(self) -> list[date]:
        now = self._now_tz()
        to_dt = now + timedelta(days=settings.MAX_RESERVATION_DAYS_AHEAD)
        candidate_dates = await self._repo.get_dates_with_available_slots(now, to_dt)
        result: list[date] = []
        for d in candidate_dates:
            grouped = await self.get_available_slots_for_date_grouped(d)
            if grouped["recommended"] or grouped["more_available"]:
                result.append(d)
        return result
