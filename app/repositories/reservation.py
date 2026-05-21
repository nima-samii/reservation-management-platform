import uuid
from datetime import datetime

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.reservation import Reservation, ReservationStatus
from app.db.models.slot import ReservationSlot
from app.repositories.base import BaseRepository


class ReservationRepository(BaseRepository[Reservation]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Reservation, session)

    async def get_user_active_reservations(
        self, user_id: uuid.UUID, now: datetime
    ) -> list[Reservation]:
        """Return upcoming active reservations for the user, sorted soonest-first."""
        stmt = (
            select(Reservation)
            .join(Reservation.slot)
            .where(
                Reservation.user_id == user_id,
                Reservation.status == ReservationStatus.ACTIVE,
                ReservationSlot.slot_datetime > now,
            )
            .options(
                selectinload(Reservation.slot),
                selectinload(Reservation.channel),
            )
            .order_by(ReservationSlot.slot_datetime.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_active_reservations(
        self, user_id: uuid.UUID, now: datetime
    ) -> int:
        """Count only future active reservations — past ones don't block new bookings."""
        stmt = (
            select(func.count(Reservation.id))
            .join(Reservation.slot)
            .where(
                Reservation.user_id == user_id,
                Reservation.status == ReservationStatus.ACTIVE,
                ReservationSlot.slot_datetime > now,
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def mark_past_reservations_completed(self, before_dt: datetime) -> int:
        """Bulk-transition active reservations whose slot has passed to COMPLETED.

        Returns the number of rows updated.
        """
        past_slot_ids = (
            select(ReservationSlot.id)
            .where(ReservationSlot.slot_datetime <= before_dt)
            .scalar_subquery()
        )
        stmt = (
            update(Reservation)
            .where(
                Reservation.status == ReservationStatus.ACTIVE,
                Reservation.slot_id.in_(past_slot_ids),
            )
            .values(status=ReservationStatus.COMPLETED)
            .execution_options(synchronize_session=False)
        )
        result = await self.session.execute(stmt)
        return result.rowcount

    async def has_reservation_on_date(
        self, user_id: uuid.UUID, target_date: datetime
    ) -> bool:
        day_start = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = target_date.replace(hour=23, minute=59, second=59, microsecond=999999)
        stmt = (
            select(Reservation.id)
            .join(Reservation.slot)
            .where(
                and_(
                    Reservation.user_id == user_id,
                    Reservation.status == ReservationStatus.ACTIVE,
                    ReservationSlot.slot_datetime >= day_start,
                    ReservationSlot.slot_datetime <= day_end,
                )
            )
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar() is not None

    async def get_reservation_with_details(
        self, reservation_id: uuid.UUID
    ) -> Reservation | None:
        stmt = (
            select(Reservation)
            .where(Reservation.id == reservation_id)
            .options(
                selectinload(Reservation.slot),
                selectinload(Reservation.channel),
                selectinload(Reservation.user),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        slot_id: uuid.UUID,
        channel_id: uuid.UUID,
    ) -> Reservation:
        reservation = Reservation(
            user_id=user_id,
            slot_id=slot_id,
            channel_id=channel_id,
            status=ReservationStatus.ACTIVE,
        )
        return await self.save(reservation)
