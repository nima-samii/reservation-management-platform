import uuid
from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy import select
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
    ) -> NotificationLog:
        entry = NotificationLog(
            reservation_id=reservation_id,
            reminder_type=reminder_type.value,
            status=status.value,
            error_message=error_message,
        )
        return await self.save(entry)

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

    async def get_reservations_for_pre_session_reminder(
        self, from_dt: datetime, to_dt: datetime
    ) -> list[Reservation]:
        """Return active reservations with slot_datetime in [from_dt, to_dt]
        that have not yet received a PRE_SESSION reminder."""
        already_sent = (
            select(NotificationLog.reservation_id)
            .where(NotificationLog.reminder_type == ReminderType.PRE_SESSION.value)
            .scalar_subquery()
        )
        stmt = (
            select(Reservation)
            .join(Reservation.slot)
            .where(
                Reservation.status == ReservationStatus.ACTIVE,
                ReservationSlot.slot_datetime >= from_dt,
                ReservationSlot.slot_datetime <= to_dt,
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
