import uuid
from datetime import datetime

import pytz
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.client import RedisClient
from app.cache.keys import CacheKey
from app.core.config import settings
from app.core.booking_rules import is_same_day_cutoff_passed
from app.core.exceptions import (
    CancellationCutoffError,
    DailyLimitError,
    MaxReservationsError,
    NotFoundError,
    PastSlotError,
    SameDayCutoffError,
    SlotUnavailableError,
)
from app.core.logging import get_logger
from app.db.models.reservation import Reservation, ReservationStatus
from app.repositories.reservation import ReservationRepository
from app.repositories.slot import SlotRepository
from app.repositories.user import UserRepository
from app.services.score import ParticipationScoreService

logger = get_logger(__name__)

TZ = pytz.timezone(settings.TIMEZONE)
SLOT_LOCK_TTL = 30  # seconds


class ReservationService:
    def __init__(self, session: AsyncSession, redis: RedisClient) -> None:
        self._session = session
        self._redis = redis
        self._res_repo = ReservationRepository(session)
        self._slot_repo = SlotRepository(session)
        self._user_repo = UserRepository(session)
        self._score_svc = ParticipationScoreService(session)

    def _now_tz(self) -> datetime:
        return datetime.now(TZ)

    async def book_slot(
        self,
        *,
        telegram_id: int,
        slot_id: uuid.UUID,
    ) -> Reservation:
        user = await self._user_repo.get_by_telegram_id(telegram_id)
        if not user:
            raise NotFoundError("User")

        lock_key = CacheKey.slot_lock(str(slot_id))
        lock_acquired = await self._redis.set_nx(lock_key, str(user.id), ttl=SLOT_LOCK_TTL)
        if not lock_acquired:
            raise SlotUnavailableError()

        try:
            return await self._perform_booking(user.id, slot_id)
        finally:
            await self._redis.delete(lock_key)

    async def _perform_booking(
        self, user_id: uuid.UUID, slot_id: uuid.UUID
    ) -> Reservation:
        try:
            slot = await self._slot_repo.get_slot_with_lock(slot_id)
        except OperationalError:
            raise SlotUnavailableError()

        if not slot:
            raise NotFoundError("Slot")

        now = self._now_tz()
        if slot.slot_datetime <= now:
            raise PastSlotError()

        slot_local_date = slot.slot_datetime.astimezone(TZ).date()
        if is_same_day_cutoff_passed(slot_local_date, now, settings.SAME_DAY_CUTOFF_HOUR):
            raise SameDayCutoffError(settings.SAME_DAY_CUTOFF_HOUR)

        if slot.is_booked:
            raise SlotUnavailableError()

        day_conflict = await self._res_repo.has_reservation_on_date(
            user_id, slot.slot_datetime
        )
        if day_conflict:
            raise DailyLimitError()

        active_count = await self._res_repo.count_active_reservations(user_id, now)
        if active_count >= settings.MAX_ACTIVE_RESERVATIONS:
            raise MaxReservationsError(settings.MAX_ACTIVE_RESERVATIONS)

        slot.is_booked = True
        await self._slot_repo.save(slot)

        reservation = await self._res_repo.create(
            user_id=user_id,
            slot_id=slot.id,
            channel_id=slot.channel_id,  # channel is encoded in the slot itself
        )

        # Re-fetch with selectinload so slot/channel are eagerly loaded.
        # Direct attribute assignment (reservation.slot = slot) is not reliable
        # in async SQLAlchemy — the ORM event system can still trigger a greenlet
        # context switch → MissingGreenlet at the handler level.
        loaded = await self._res_repo.get_reservation_with_details(reservation.id)

        await self._score_svc.award_reservation_reward(user_id, reservation.id)

        logger.info(
            "reservation_created",
            user_id=str(user_id),
            slot=str(slot.slot_datetime),
            channel_id=str(slot.channel_id),
        )
        return loaded  # type: ignore[return-value]

    async def cancel_reservation(
        self, *, telegram_id: int, reservation_id: uuid.UUID
    ) -> None:
        user = await self._user_repo.get_by_telegram_id(telegram_id)
        if not user:
            raise NotFoundError("User")

        reservation = await self._res_repo.get_reservation_with_details(reservation_id)
        if not reservation:
            raise NotFoundError("Reservation")

        if reservation.user_id != user.id:
            raise NotFoundError("Reservation")

        if reservation.status != ReservationStatus.ACTIVE:
            raise ValueError("Only active reservations can be cancelled.")

        now = self._now_tz()
        if reservation.slot.slot_datetime <= now:
            raise PastSlotError()

        slot_local_date = reservation.slot.slot_datetime.astimezone(TZ).date()
        if is_same_day_cutoff_passed(slot_local_date, now, settings.SAME_DAY_CANCEL_CUTOFF_HOUR):
            raise CancellationCutoffError(settings.SAME_DAY_CANCEL_CUTOFF_HOUR)

        reservation.status = ReservationStatus.CANCELLED
        reservation.slot.is_booked = False

        await self._res_repo.save(reservation)
        await self._slot_repo.save(reservation.slot)

        await self._score_svc.rollback_cancellation(user.id, reservation_id)

        logger.info(
            "reservation_cancelled",
            user_id=str(user.id),
            reservation_id=str(reservation_id),
        )

    async def get_user_reservations(self, telegram_id: int) -> list[Reservation]:
        user = await self._user_repo.get_by_telegram_id(telegram_id)
        if not user:
            raise NotFoundError("User")
        now = self._now_tz()
        return await self._res_repo.get_user_active_reservations(user.id, now)

    async def complete_past_reservations(self) -> int:
        """Transition active reservations whose slot has passed to COMPLETED.

        Called by the scheduler job; returns the count of updated rows.
        """
        now = self._now_tz()
        count = await self._res_repo.mark_past_reservations_completed(now)
        if count:
            logger.info("reservations_completed", count=count)
        return count
