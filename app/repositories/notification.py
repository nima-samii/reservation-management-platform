import uuid
from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.db.models.notification_log import DeliveryStatus, NotificationLog, ReminderType
from app.db.models.reservation import Reservation, ReservationStatus
from app.db.models.slot import ReservationSlot
from app.repositories.base import BaseRepository


class NotificationRepository(BaseRepository[NotificationLog]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(NotificationLog, session)

    async def log(
        self,
        reservation_id: uuid.UUID,
        reminder_type: ReminderType,
        status: DeliveryStatus,
        error_message: str | None = None,
    ) -> None:
        """Record the outcome of a reminder send.

        Upsert on the ``(reservation_id, reminder_type)`` unique constraint: a
        first attempt inserts; a retry after an earlier FAILED attempt overwrites
        that row in place. This keeps the existing unique constraint intact (no
        migration) while letting the time-window queries retry failures — a SENT
        row is never revisited because those queries filter it out before we ever
        try to send again.
        """
        stmt = (
            pg_insert(NotificationLog)
            .values(
                reservation_id=reservation_id,
                reminder_type=reminder_type.value,
                status=status.value,
                error_message=error_message,
            )
            .on_conflict_do_update(
                constraint="uq_notification_log_reservation_type",
                set_={
                    "status": status.value,
                    "error_message": error_message,
                    "sent_at": sa.func.now(),
                },
            )
        )
        await self.session.execute(stmt)

    async def get_for_reservation(
        self, reservation_id: uuid.UUID
    ) -> list[NotificationLog]:
        """All notification-delivery rows for a reservation, oldest first.

        Read-only — used by the reservation timeline builder."""
        stmt = (
            select(NotificationLog)
            .where(NotificationLog.reservation_id == reservation_id)
            .order_by(NotificationLog.sent_at.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_reservations_for_same_day_reminder(
        self, target_date: date
    ) -> list[Reservation]:
        """Return active reservations whose slot falls on target_date (Baghdad tz)
        and that have not yet received a SAME_DAY reminder."""
        already_sent = (
            select(NotificationLog.reservation_id)
            .where(NotificationLog.reminder_type == ReminderType.SAME_DAY.value)
            .scalar_subquery()
        )
        stmt = (
            select(Reservation)
            .join(Reservation.slot)
            .where(
                Reservation.status == ReservationStatus.ACTIVE,
                sa.cast(
                    sa.func.timezone(settings.TIMEZONE, ReservationSlot.slot_datetime),
                    sa.Date,
                )
                == target_date,
                Reservation.id.not_in(already_sent),
            )
            .options(
                selectinload(Reservation.user),
                selectinload(Reservation.slot).selectinload(ReservationSlot.channel),
            )
            .order_by(ReservationSlot.slot_datetime.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_reservations_for_window_reminder(
        self,
        reminder_type: ReminderType,
        from_dt: datetime,
        to_dt: datetime,
        *,
        upper_inclusive: bool = True,
    ) -> list[Reservation]:
        """Return active reservations whose slot falls in a time window and that
        have not yet been *successfully* sent ``reminder_type``.

        The window is ``[from_dt, to_dt]`` by default, or ``[from_dt, to_dt)``
        when ``upper_inclusive`` is False (the forward-only window the final
        reminder uses so it never fires early).

        Deduplication keys on SENT logs only: a FAILED row stays eligible, so a
        transient failure is retried on the next tick while the reservation is
        still inside the window — without ever re-sending a delivered reminder
        (the paired upsert in :meth:`log` overwrites the FAILED row on retry).

        Shared by the pre-session and final reminders; future time-window
        reminder types reuse it by passing their own ``reminder_type`` and window.
        """
        already_sent = (
            select(NotificationLog.reservation_id)
            .where(
                NotificationLog.reminder_type == reminder_type.value,
                NotificationLog.status == DeliveryStatus.SENT.value,
            )
            .scalar_subquery()
        )
        upper_bound = (
            ReservationSlot.slot_datetime <= to_dt
            if upper_inclusive
            else ReservationSlot.slot_datetime < to_dt
        )
        stmt = (
            select(Reservation)
            .join(Reservation.slot)
            .where(
                Reservation.status == ReservationStatus.ACTIVE,
                ReservationSlot.slot_datetime >= from_dt,
                upper_bound,
                Reservation.id.not_in(already_sent),
            )
            .options(
                selectinload(Reservation.user),
                selectinload(Reservation.slot).selectinload(ReservationSlot.channel),
            )
            .order_by(ReservationSlot.slot_datetime.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
