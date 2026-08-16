import uuid
from datetime import datetime

import pytz
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.client import RedisClient
from app.cache.keys import CacheKey
from app.core.config import settings
from app.core.booking_rules import is_same_day_cutoff_passed
from app.core.exceptions import (
    CancellationCutoffError,
    DailyLimitError,
    DuplicateSlotTimeError,
    MaxReservationsError,
    NotFoundError,
    PastSlotError,
    ReservationNotCancellableError,
    SameDayCutoffError,
    SlotUnavailableError,
    UserBannedError,
)
from app.core.logging import get_logger
from app.db.models.reservation import Reservation, ReservationStatus
from app.repositories.channel import ChannelRepository
from app.repositories.reservation import ReservationRepository
from app.repositories.slot import SlotRepository
from app.repositories.user import UserRepository
from app.schedulers.jobs.reservation_notification import (
    enqueue_reservation_cancellation_notification,
    enqueue_reservation_creation_notification,
)
from app.schedulers.jobs.score_notification import enqueue_score_notification
from app.services.score import ParticipationScoreService
from app.services.strategies.base import SlotRef, SlotResolutionStrategy
from app.services.strategies.explicit import ExplicitSlotStrategy
from app.services.strategies.resolver import get_reservation_strategy

logger = get_logger(__name__)

TZ = pytz.timezone(settings.TIMEZONE)
SLOT_LOCK_TTL = 30  # seconds


class ReservationService:
    def __init__(self, session: AsyncSession, redis: RedisClient) -> None:
        self._session = session
        self._redis = redis
        self._res_repo = ReservationRepository(session)
        self._slot_repo = SlotRepository(session)
        self._channel_repo = ChannelRepository(session)
        self._user_repo = UserRepository(session)
        self._score_svc = ParticipationScoreService(session)

    def _now_tz(self) -> datetime:
        return datetime.now(TZ)

    @staticmethod
    def _contended_resource(
        user_id: uuid.UUID,
        slot_ref: SlotRef,
        strategy: SlotResolutionStrategy | None,
    ) -> str:
        """What the advisory lock in ``_book`` should serialise on.

        Under identity resolution (no strategy, EXPLICIT, THRESHOLD_UNLOCK) the
        booking claims exactly the referenced row, so that id is the contended
        resource and the key is unchanged from before strategies existed.

        A strategy that re-picks the row cannot use it. Every user referencing
        a given time — whether by ``lslot:HH:MM`` or by the same representative
        uuid — intends to land on a *different* row, so locking that shared
        reference would reject a booking the database could have satisfied on
        the next channel down. The row-level ``FOR UPDATE ... SKIP LOCKED`` is
        the real serialisation point there, and it is per-row and therefore
        exactly right.

        Scoping the key to the user keeps the one guarantee the slot-id key
        still provided: a double-tapped confirm button is one booking, not two
        on two channels.
        """
        if strategy is None or strategy.resolves_by_identity:
            return str(slot_ref)
        return f"{user_id}:{slot_ref}"

    async def _book(
        self,
        user_id: uuid.UUID,
        slot_ref: SlotRef,
        *,
        strategy: SlotResolutionStrategy | None = None,
    ) -> Reservation:
        """Slot-locked booking core shared by the user and admin entry points.

        Acquires the per-slot Redis lock, then delegates to ``_perform_booking``
        which is the single implementation of all booking validation, slot
        claiming and reservation creation. Neither entry point may bypass this.

        Omitting ``strategy`` books exactly the referenced row. That default is
        what keeps the admin path honest: it never passes a strategy, so no
        configured strategy can reassign the channel an admin chose.
        """
        lock_key = CacheKey.slot_lock(self._contended_resource(user_id, slot_ref, strategy))
        lock_acquired = await self._redis.set_nx(lock_key, str(user_id), ttl=SLOT_LOCK_TTL)
        if not lock_acquired:
            raise SlotUnavailableError()

        try:
            return await self._perform_booking(user_id, slot_ref, strategy=strategy)
        finally:
            await self._redis.delete(lock_key)

    async def book_slot(
        self,
        *,
        telegram_id: int,
        slot_ref: SlotRef,
    ) -> Reservation:
        """Book on behalf of a Telegram user.

        ``slot_ref`` is whatever the tapped button named — a physical slot id,
        or a time when the configured strategy chooses the channel itself. The
        two are not interchangeable, and it is the strategy that decides which
        it can honour; see :data:`SlotRef`.
        """
        user = await self._user_repo.get_by_telegram_id(telegram_id)
        if not user:
            raise NotFoundError("User")
        # The user-facing flow is the only entry point that honours the
        # configured strategy.
        strategy = get_reservation_strategy(
            slot_repo=self._slot_repo,
            channel_repo=self._channel_repo,
        )
        return await self._book(user.id, slot_ref, strategy=strategy)

    async def admin_create_reservation(
        self,
        *,
        user_id: uuid.UUID,
        slot_id: uuid.UUID,
        actor: str,
    ) -> Reservation:
        """Book a slot on behalf of an existing user from the admin panel.

        Goes through the exact same booking core as user booking (``_book`` →
        ``_perform_booking``): identical locking, validation (daily limit, max
        active, duplicate time, double-booking, past-slot, same-day cutoff) and
        the standard +1 score reward. The only admin-specific additions are the up-front
        existence/ban checks and an out-of-band confirmation DM (the user is not
        in a chat flow, so unlike user booking there is no inline confirmation).

        Deliberately passes no strategy: an admin picked the channel, and no
        configured reservation strategy may override that choice.
        """
        user = await self._user_repo.get_by_id(user_id)
        if not user:
            raise NotFoundError("User")
        if user.is_banned:
            raise UserBannedError()

        reservation = await self._book(user.id, slot_id)

        # Deliver the confirmation only after the surrounding transaction
        # commits (the delayed job runs in its own session); a failed send
        # never rolls back the booking.
        enqueue_reservation_creation_notification(reservation.id)

        logger.info(
            "admin_reservation_created",
            reservation_id=str(reservation.id),
            user_id=str(user.id),
            admin=actor,
        )
        return reservation

    async def _perform_booking(
        self,
        user_id: uuid.UUID,
        slot_ref: SlotRef,
        *,
        strategy: SlotResolutionStrategy | None = None,
    ) -> Reservation:
        """The single implementation of booking, shared by both entry points.

        Locks are taken in a fixed order — **user row, then slot row** — and
        every booking path goes through here, so no two bookings can acquire
        them in opposite orders and deadlock. Anything added later that needs
        both must keep this order.
        """
        # Serialises this user's concurrent bookings for the rest of the
        # transaction, so the per-user checks below (daily limit, max active)
        # are read-then-write against state nobody else can change underneath
        # them. Taken before slot resolution to fix the lock order; see
        # UserRepository.get_by_id_for_update for why the Redis lock and the
        # per-slot row locks cannot serve this purpose.
        locked_user = await self._user_repo.get_by_id_for_update(user_id)
        if not locked_user:
            raise NotFoundError("User")

        # Picking the physical slot is the only part of booking a strategy may
        # change; everything below is shared and must stay identical for all of
        # them. Defaults to booking exactly the referenced row.
        resolution = strategy or ExplicitSlotStrategy(self._slot_repo)
        slot = await resolution.resolve_slot(slot_ref)

        now = self._now_tz()
        if slot.slot_datetime <= now:
            raise PastSlotError()

        slot_local_date = slot.slot_datetime.astimezone(TZ).date()
        if is_same_day_cutoff_passed(slot_local_date, now, settings.SAME_DAY_CUTOFF_HOUR):
            raise SameDayCutoffError(settings.SAME_DAY_CUTOFF_HOUR)

        if slot.is_booked:
            raise SlotUnavailableError()

        # Counted against the *local* calendar day, reusing the same
        # slot_local_date the cutoff rule above was evaluated on — the two must
        # never disagree about which day a slot belongs to.
        daily_count = await self._res_repo.count_reservations_on_date(
            user_id, slot_local_date
        )
        if daily_count >= settings.MAX_DAILY_RESERVATIONS:
            raise DailyLimitError(settings.MAX_DAILY_RESERVATIONS)

        active_count = await self._res_repo.count_active_reservations(user_id, now)
        if active_count >= settings.MAX_ACTIVE_RESERVATIONS:
            raise MaxReservationsError(settings.MAX_ACTIVE_RESERVATIONS)

        # Checked against the *resolved* row's time, not the requested one, so
        # it holds for a strategy that re-picks the channel as much as for one
        # that books what was named.
        #
        # Deliberately last of the three. The two caps above are blanket blocks
        # on the day and on the user, and this error tells the user to pick a
        # different time — advice that would be false if either cap were the
        # thing actually stopping them.
        if await self._res_repo.has_reservation_at_time(user_id, slot.slot_datetime):
            raise DuplicateSlotTimeError(
                slot.slot_datetime.astimezone(TZ).strftime("%I:%M %p")
            )

        slot.is_booked = True
        await self._slot_repo.save(slot)

        reservation = await self._res_repo.create(
            user_id=user_id,
            slot_id=slot.id,
            channel_id=slot.channel_id,  # channel is encoded in the slot itself
        )

        # Reset the inactivity-reminder cycle — any successful booking (user
        # or admin-initiated) refreshes this; cancellation deliberately does not.
        await self._user_repo.set_last_reservation_at(user_id, now)

        # Re-fetch with selectinload so slot/channel are eagerly loaded.
        # Direct attribute assignment (reservation.slot = slot) is not reliable
        # in async SQLAlchemy — the ORM event system can still trigger a greenlet
        # context switch → MissingGreenlet at the handler level.
        loaded = await self._res_repo.get_reservation_with_details(reservation.id)

        tx = await self._score_svc.award_reservation_reward(user_id, reservation.id)
        enqueue_score_notification(tx.id, tx.transaction_type)

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

        # Atomic race guard: only the winner of a concurrent cancel proceeds, so
        # a double-tapped confirm button (or a user cancel racing an admin
        # cancel) can never deduct the score twice or free the slot twice.
        won = await self._res_repo.transition_active_to_cancelled(reservation_id)
        if not won:
            raise ValueError("This reservation has already been cancelled.")

        reservation.status = ReservationStatus.CANCELLED
        reservation.slot.is_booked = False
        await self._slot_repo.save(reservation.slot)

        tx = await self._score_svc.rollback_cancellation(user.id, reservation_id)
        enqueue_score_notification(tx.id, tx.transaction_type)

        logger.info(
            "reservation_cancelled",
            user_id=str(user.id),
            reservation_id=str(reservation_id),
        )

    async def admin_cancel_reservation(
        self,
        reservation_id: uuid.UUID,
        actor: str,
        reason: str | None = None,
    ) -> Reservation:
        """Cancel a reservation on behalf of an admin.

        Reuses the shared cancellation flow (status flip + slot release) and
        rolls back the booking's +1 reward (-1), so an admin cancellation leaves
        the user's score as if the reservation had never been made. Records the
        acting admin, reason and timestamp, then enqueues a user-facing DM that
        is delivered out-of-band after this request's transaction commits.
        """
        reservation = await self._res_repo.get_reservation_admin_detail(reservation_id)
        if not reservation:
            raise NotFoundError("Reservation")

        if reservation.status != ReservationStatus.ACTIVE:
            raise ReservationNotCancellableError(reservation.status)

        # Atomic race guard: fold the status flip and the actor metadata into a
        # single conditional UPDATE. If we lose the race to a concurrent cancel
        # or to the lifecycle-completion job (which turns a just-passed slot to
        # COMPLETED), rowcount is 0 and we must not roll back the score again.
        cancelled_at = self._now_tz()
        won = await self._res_repo.transition_active_to_cancelled(
            reservation_id,
            cancelled_by=actor,
            cancelled_at=cancelled_at,
            cancellation_reason=reason,
        )
        if not won:
            raise ReservationNotCancellableError(reservation.status)

        # Reflect the committed change on the in-memory instance for the response
        # and free the slot.
        reservation.status = ReservationStatus.CANCELLED
        reservation.cancelled_by = actor
        reservation.cancelled_at = cancelled_at
        reservation.cancellation_reason = reason
        reservation.slot.is_booked = False
        await self._slot_repo.save(reservation.slot)

        # Roll back the +1 earned at booking. The dedicated cancellation DM
        # below already informs the user, so we deliberately do NOT raise a
        # second "Score Update" DM here (RESERVATION_CANCELLATION is gated off
        # by NOTIFY_ON_CANCEL_ROLLBACK; enqueue self-filters accordingly).
        tx = await self._score_svc.rollback_cancellation(
            reservation.user_id, reservation.id
        )
        enqueue_score_notification(tx.id, tx.transaction_type)

        # Deliver the DM only after the surrounding transaction commits (the
        # delayed job runs in its own session); a failed send never rolls back
        # the cancellation.
        enqueue_reservation_cancellation_notification(reservation.id, reason)

        logger.info(
            "admin_reservation_cancelled",
            reservation_id=str(reservation_id),
            admin=actor,
        )
        return reservation

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
