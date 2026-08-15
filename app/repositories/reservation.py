import json
import uuid
from datetime import date, datetime, time, timedelta

import pytz
import sqlalchemy as sa
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.db.models.reservation import Reservation, ReservationStatus
from app.db.models.slot import ReservationSlot
from app.db.models.user import User
from app.repositories.base import BaseRepository

TZ = pytz.timezone(settings.TIMEZONE)


def _parse_notes(notes: str | None) -> dict:
    """Parse notes as JSON dict. Plain-string notes are wrapped to preserve them."""
    if not notes:
        return {}
    try:
        parsed = json.loads(notes)
        if isinstance(parsed, dict):
            return parsed
        # JSON but not a dict (e.g. a JSON string literal) — wrap it
        return {"original_notes": notes}
    except (json.JSONDecodeError, TypeError, ValueError):
        # Plain text from bot — wrap so it isn't lost on merge
        return {"original_notes": notes}


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

    async def transition_active_to_cancelled(
        self,
        reservation_id: uuid.UUID,
        *,
        cancelled_by: str | None = None,
        cancelled_at: datetime | None = None,
        cancellation_reason: str | None = None,
    ) -> bool:
        """Atomically flip an ACTIVE reservation to CANCELLED.

        The conditional ``WHERE status = 'active'`` is the race guard: two
        concurrent cancellations (a double-tapped inline button, or a user
        cancel racing an admin cancel / the lifecycle-completion job) serialize
        on the row lock, and only the first observes ``rowcount == 1``. The loser
        observes ``rowcount == 0`` and must NOT apply a second score rollback or
        write a duplicate audit row. Returns True iff this caller won the
        transition.
        """
        values: dict = {"status": ReservationStatus.CANCELLED}
        if (
            cancelled_by is not None
            or cancelled_at is not None
            or cancellation_reason is not None
        ):
            values["cancelled_by"] = cancelled_by
            values["cancelled_at"] = cancelled_at
            values["cancellation_reason"] = cancellation_reason

        stmt = (
            update(Reservation)
            .where(
                Reservation.id == reservation_id,
                Reservation.status == ReservationStatus.ACTIVE,
            )
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        result = await self.session.execute(stmt)
        return (result.rowcount or 0) > 0

    async def count_reservations_on_date(
        self, user_id: uuid.UUID, local_date: date
    ) -> int:
        """Count a user's reservations falling on a *local* calendar day.

        Takes the local date, not a datetime. The predecessor derived the day
        window from a slot's ``slot_datetime``, which asyncpg hands back as
        UTC — so "day" silently meant the UTC calendar day. With slots at
        16:00-23:59 Asia/Baghdad (13:00-20:59 UTC) the two coincide and the bug
        never showed, but SLOT_START_HOUR is admin-editable down to 0, and a
        local 00:00-02:59 slot lands on the *previous* UTC day.

        Bounds are two independently localized midnights rather than
        ``start + 24h``: a local day is not 24 hours long across a DST
        transition. Asia/Baghdad has no DST today; this must not depend on that.

        The window compares the indexed column directly instead of using the
        ``cast(timezone(TZ, slot_datetime), Date) == :d`` form the admin-list
        queries below use. Both are correct, but a cast over the column is not
        sargable — this form can use the btree index on ``slot_datetime``.

        Half-open ``[start, end)``: the old ``<= 23:59:59.999999`` sentinel
        could miss a slot in the final fraction of a second.
        """
        day_start = TZ.localize(datetime.combine(local_date, time.min))
        day_end = TZ.localize(
            datetime.combine(local_date + timedelta(days=1), time.min)
        )
        stmt = (
            select(func.count(Reservation.id))
            .join(Reservation.slot)
            .where(
                Reservation.user_id == user_id,
                Reservation.status == ReservationStatus.ACTIVE,
                ReservationSlot.slot_datetime >= day_start,
                ReservationSlot.slot_datetime < day_end,
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar() or 0

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

    async def get_reservation_admin_detail(
        self, reservation_id: uuid.UUID
    ) -> Reservation | None:
        """Full eager load including user.country_rel — for admin detail endpoint."""
        stmt = (
            select(Reservation)
            .where(Reservation.id == reservation_id)
            .options(
                selectinload(Reservation.slot),
                selectinload(Reservation.channel),
                selectinload(Reservation.user).selectinload(User.country_rel),
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

    async def get_active_reservations_for_date_and_channel(
        self, channel_id: uuid.UUID, target_date: date
    ) -> list[Reservation]:
        """Return all ACTIVE reservations for a specific channel on target_date (Baghdad tz),
        sorted by slot time. Eagerly loads user→country and slot for broadcast rendering."""
        stmt = (
            select(Reservation)
            .join(Reservation.slot)
            .where(
                Reservation.channel_id == channel_id,
                Reservation.status == ReservationStatus.ACTIVE,
                sa.cast(
                    sa.func.timezone(settings.TIMEZONE, ReservationSlot.slot_datetime),
                    sa.Date,
                )
                == target_date,
            )
            .options(
                selectinload(Reservation.user).selectinload(User.country_rel),
                selectinload(Reservation.slot),
            )
            .order_by(ReservationSlot.slot_datetime.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    # ── Admin list helpers ────────────────────────────────────────────────

    def _build_admin_filters(
        self,
        date_single: date | None,
        date_from: date | None,
        date_to: date | None,
        channel_id: uuid.UUID | None,
        status: str | None,
        search: str | None,
    ) -> list:
        filters: list = []

        local_date_expr = sa.cast(
            sa.func.timezone(settings.TIMEZONE, ReservationSlot.slot_datetime),
            sa.Date,
        )

        if date_single is not None:
            filters.append(local_date_expr == date_single)
        else:
            if date_from is not None:
                filters.append(local_date_expr >= date_from)
            if date_to is not None:
                filters.append(local_date_expr <= date_to)

        if channel_id is not None:
            filters.append(Reservation.channel_id == channel_id)

        if status is not None:
            filters.append(Reservation.status == status)

        if search and search.strip():
            pattern = f"%{search.strip()}%"
            filters.append(
                sa.or_(
                    User.full_name.ilike(pattern),
                    User.public_user_code.ilike(pattern),
                )
            )

        return filters

    async def admin_list(
        self,
        *,
        date_single: date | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        channel_id: uuid.UUID | None = None,
        status: str | None = None,
        search: str | None = None,
        page: int = 1,
        page_size: int = 100,
    ) -> tuple[list[Reservation], int]:
        filters = self._build_admin_filters(
            date_single, date_from, date_to, channel_id, status, search
        )

        count_stmt = (
            select(func.count(Reservation.id))
            .join(Reservation.slot)
            .join(Reservation.user)
        )
        if filters:
            count_stmt = count_stmt.where(*filters)
        total = (await self.session.execute(count_stmt)).scalar() or 0

        stmt = (
            select(Reservation)
            .join(Reservation.slot)
            .join(Reservation.user)
        )
        if filters:
            stmt = stmt.where(*filters)
        stmt = (
            stmt.options(
                selectinload(Reservation.slot),
                selectinload(Reservation.channel),
                selectinload(Reservation.user).selectinload(User.country_rel),
            )
            .order_by(ReservationSlot.slot_datetime.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def admin_summary(
        self,
        *,
        date_single: date | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        channel_id: uuid.UUID | None = None,
        search: str | None = None,
    ) -> dict:
        """Count reservations by status for the given filters (status filter excluded)."""
        filters = self._build_admin_filters(
            date_single, date_from, date_to, channel_id, None, search
        )

        stmt = (
            select(Reservation.status, Reservation.notes)
            .join(Reservation.slot)
            .join(Reservation.user)
        )
        if filters:
            stmt = stmt.where(*filters)

        rows = (await self.session.execute(stmt)).all()

        total = len(rows)
        active = sum(1 for r in rows if r.status == ReservationStatus.ACTIVE)
        completed = sum(1 for r in rows if r.status == ReservationStatus.COMPLETED)
        cancelled = sum(1 for r in rows if r.status == ReservationStatus.CANCELLED)
        no_show = sum(
            1 for r in rows
            if _parse_notes(r.notes).get("no_show_penalty_applied") is True
        )

        return {
            "total": total,
            "active": active,
            "completed": completed,
            "cancelled": cancelled,
            "no_show": no_show,
        }

    async def admin_export(
        self,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
        channel_id: uuid.UUID | None = None,
        status: str | None = None,
    ) -> list[Reservation]:
        filters = self._build_admin_filters(
            None, date_from, date_to, channel_id, status, None
        )

        stmt = (
            select(Reservation)
            .join(Reservation.slot)
            .join(Reservation.user)
        )
        if filters:
            stmt = stmt.where(*filters)

        stmt = (
            stmt.options(
                selectinload(Reservation.slot),
                selectinload(Reservation.channel),
                selectinload(Reservation.user).selectinload(User.country_rel),
            )
            .order_by(ReservationSlot.slot_datetime.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
