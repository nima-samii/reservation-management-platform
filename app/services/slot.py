import uuid
from datetime import date, datetime, timedelta

import pytz
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.booking_rules import is_same_day_cutoff_passed
from app.core.config import settings
from app.core.logging import get_logger
from app.db.models.slot import ReservationSlot
from app.repositories.channel import ChannelRepository
from app.repositories.slot import SlotRepository
from app.services.strategies.base import GroupedSlots
from app.services.strategies.resolver import get_reservation_strategy

logger = get_logger(__name__)

TZ = pytz.timezone(settings.TIMEZONE)

__all__ = ["GroupedSlots", "SlotService"]


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

    async def generate_slots_for_channel(
        self, channel_id: uuid.UUID, days: int
    ) -> int:
        """Generate the next `days` of slots for a single channel.

        Called right after a channel is created so it has bookable slots
        immediately, instead of waiting for the nightly slot-generation cron.
        Idempotent: existing (datetime, channel) slots are skipped.
        """
        today = self._now_tz().date()
        created = 0
        for i in range(days):
            target = today + timedelta(days=i)
            for dt in self._generate_slot_datetimes(target):
                if not await self._repo.slot_exists_for_datetime_and_channel(
                    dt, channel_id
                ):
                    await self._repo.save(
                        ReservationSlot(slot_datetime=dt, channel_id=channel_id)
                    )
                    created += 1
        if created:
            logger.info(
                "slots_generated_for_channel",
                channel_id=str(channel_id),
                count=created,
            )
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
        """Slots offered for a date, grouped into the two keyboard sections.

        The same-day cutoff is a shared reservation rule — it holds for every
        strategy and is also re-checked at booking time — so it is enforced
        here, before delegating. What is left is the strategy's own decision:
        which channels are open and which of their slots to offer.
        """
        now = self._now_tz()

        if is_same_day_cutoff_passed(slot_date, now, settings.SAME_DAY_CUTOFF_HOUR):
            return GroupedSlots(recommended=[], more_available=[])

        # Built per call, not cached on the service: the admin panel mutates the
        # settings singleton at runtime, so the strategy must be re-read rather
        # than frozen at construction time.
        strategy = get_reservation_strategy(
            slot_repo=self._repo,
            channel_repo=self._channel_repo,
            config=settings,
        )
        return await strategy.list_bookable_slots(slot_date, now=now)

    def offers_slots_by_time(self) -> bool:
        """Whether a slot button should name a *time* rather than a slot row.

        A button has to name whatever the configured strategy is going to
        resolve, so this is the same question as ``resolves_by_identity`` — read
        from the strategy rather than from ``RESERVATION_STRATEGY`` so the
        keyboard and the booking path can never disagree about the callback
        format. Built per call for the same reason as the listing above: the
        admin panel can switch strategies at runtime.
        """
        strategy = get_reservation_strategy(
            slot_repo=self._repo,
            channel_repo=self._channel_repo,
            config=settings,
        )
        return not strategy.resolves_by_identity

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
