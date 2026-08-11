import uuid
from datetime import date, datetime

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.channel import Channel
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

    async def get_distinct_open_slots_for_date(
        self, target_date: date, tz_now: datetime
    ) -> list[ReservationSlot]:
        """One open slot per distinct clock time on a date, across all channels.

        SEQUENTIAL_FILL offers each time exactly once no matter how many
        channels still have that time free. ``DISTINCT ON (slot_datetime)``
        with ``ORDER BY slot_datetime, channel.priority`` picks the
        highest-priority channel's row for each time.

        The row returned is a *representative*, not a reservation: by the time
        the user taps it another booking may have claimed it. Resolution re-runs
        the priority pick under a row lock
        (:meth:`lock_next_slot_by_priority`), so the representative only has to
        carry the right ``slot_datetime``.

        Filters mirror get_available_slots_for_date_and_channel (same day
        bounds, unbooked, strictly in the future) and additionally exclude
        inactive channels, which must never receive a sequential booking.
        """
        day_start, day_end = self._day_bounds(target_date, tz_now.tzinfo)
        stmt = (
            select(ReservationSlot)
            .join(Channel, Channel.id == ReservationSlot.channel_id)
            .where(
                and_(
                    ReservationSlot.slot_datetime >= day_start,
                    ReservationSlot.slot_datetime <= day_end,
                    ReservationSlot.slot_datetime > tz_now,
                    ReservationSlot.is_booked == False,  # noqa: E712
                    Channel.is_active == True,  # noqa: E712
                )
            )
            .distinct(ReservationSlot.slot_datetime)
            .order_by(
                ReservationSlot.slot_datetime.asc(),
                Channel.priority.asc(),
                ReservationSlot.id.asc(),
            )
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def lock_next_slot_by_priority(
        self, slot_datetime: datetime
    ) -> ReservationSlot | None:
        """Claim the highest-priority free slot at an exact time, atomically.

        Emits ``FOR UPDATE OF reservation_slots SKIP LOCKED ... LIMIT 1``. The
        three parts each do a job:

        * ``OF reservation_slots`` — locks only the slot row. Locking the joined
          channel row too would serialise every booking on that channel.
        * ``SKIP LOCKED`` — a slot another transaction is mid-booking is passed
          over rather than waited on, so concurrent bookings for the same time
          cascade down the priority order instead of queueing. This is what
          makes sequential fill concurrent; ``NOWAIT`` would reject the second
          booker even though a lower-priority channel was free.
        * ``LIMIT 1`` above the lock — Postgres pulls rows through the lock node
          until one is successfully locked, so the limit does not cut the scan
          short at a row that was skipped.

        Rows updated *and committed* by a competing transaction are re-checked
        against the WHERE clause when the lock is taken, so a slot booked a
        moment ago is excluded rather than returned stale. Verified against a
        real server in tests/test_repositories/test_slot_priority_lock.py.

        Returns None when every channel is taken at that time — the caller
        turns that into SlotUnavailableError.
        """
        stmt = (
            select(ReservationSlot)
            .join(Channel, Channel.id == ReservationSlot.channel_id)
            .where(
                and_(
                    ReservationSlot.slot_datetime == slot_datetime,
                    ReservationSlot.is_booked == False,  # noqa: E712
                    Channel.is_active == True,  # noqa: E712
                )
            )
            # id breaks ties so two channels sharing a priority still resolve
            # deterministically rather than by physical row order.
            .order_by(Channel.priority.asc(), ReservationSlot.id.asc())
            .limit(1)
            .with_for_update(skip_locked=True, of=ReservationSlot)
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
