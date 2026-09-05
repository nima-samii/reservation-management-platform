import json
import uuid
from datetime import date, datetime, time, timedelta

import pytz
import sqlalchemy as sa
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.db.models.reservation import AttendanceStatus, Reservation, ReservationStatus
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


# ── "Was this session missed?" — one definition, two dialects ─────────────────
#
# Two mechanisms can say a session was not attended, and both are authoritative
# for the rows they wrote: `attendance_status = 'absent'` (current) and the
# `notes["no_show_penalty_applied"]` flag left by the retired no-show endpoint.
# Every counter, filter and export that reports absences goes through the
# helpers below, because counting only one of the two is wrong in one direction
# or the other — read only the flag and the number flatlines at zero as new
# decisions come in; read only the column and every historical absence
# disappears from the record.
#
# The flag lives inside `notes`, a plain String column, written by exactly one
# line: json.dumps({..., "no_show_penalty_applied": True}), which always
# renders as '"no_show_penalty_applied": true'. A substring match is therefore
# reliable, and it is the only way to reach the flag from SQL — the column is
# not JSONB, so there is nothing to index or extract.
_LEGACY_NO_SHOW_PATTERN = '%"no_show_penalty_applied": true%'


def was_absent(attendance_status: str | None, notes: str | None) -> bool:
    """True when a reservation is on record as not attended, under either system.

    Takes the two values rather than a row so the call site has to name them:
    the dashboard queries select an explicit column list, and a column someone
    forgot to add should fail loudly there instead of silently reading as
    "attended" inside a shared helper.
    """
    if attendance_status == AttendanceStatus.ABSENT.value:
        return True
    return _parse_notes(notes).get("no_show_penalty_applied") is True


def legacy_no_show_sql():
    """SQL form of the legacy flag alone — true only where the flag is set."""
    return Reservation.notes.like(_LEGACY_NO_SHOW_PATTERN)


def not_legacy_no_show_sql():
    """NULL-safe negation of the above.

    `notes` is NULL for the great majority of rows, and `NOT (NULL LIKE ...)`
    is NULL rather than TRUE — which silently drops exactly the rows that most
    obviously never had a penalty.
    """
    return sa.or_(Reservation.notes.is_(None), sa.not_(legacy_no_show_sql()))


def absent_sql():
    """SQL form of :func:`was_absent`."""
    return sa.or_(
        Reservation.attendance_status == AttendanceStatus.ABSENT.value,
        legacy_no_show_sql(),
    )


def not_absent_sql():
    """NULL-safe negation of :func:`absent_sql` — attended, or not yet decided."""
    return sa.and_(
        sa.or_(
            Reservation.attendance_status.is_(None),
            Reservation.attendance_status != AttendanceStatus.ABSENT.value,
        ),
        not_legacy_no_show_sql(),
    )


# Attendance filters the admin list accepts. Exported so the API can reject an
# unknown value with a 422 that names the valid ones, rather than silently
# returning an unfiltered page.
ATTENDANCE_FILTERS = ("pending", "decided", "attended", "absent")


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

    async def claim_attendance_decision(
        self,
        reservation_id: uuid.UUID,
        *,
        attendance_status: str,
        score_delta: int,
        reason: str,
        marked_by: str,
        marked_at: datetime,
    ) -> bool:
        """Atomically record the one attendance decision a reservation may have.

        The same shape as :meth:`transition_active_to_cancelled`, and for the
        same reason: the decision applies a score, so it must happen at most
        once no matter how many concurrent requests ask for it. Two admins
        clicking "Did not attend" on the same row — or one admin's
        double-tapped button — serialize on the row lock, and only the first
        observes ``rowcount == 1``. Returns True iff this caller won.

        ``attendance_status IS NULL`` is the guard, so the claim is what makes
        the decision exist; there is no separate flag to keep in step with it.
        This is the specific defect it exists to prevent: the legacy no-show
        endpoint reads ``notes``, checks its flag, applies the penalty and only
        then writes the flag back, all without a lock — two requests both read
        an unflagged row and both charge the user.

        Callers **must** claim before touching the score ledger. The legacy
        path scores first and flags second, so a crash between the two leaves a
        charge that the next request cannot see and will happily repeat.

        Requiring ``status = 'completed'`` keeps the rule that only a session
        that actually ran can be judged — an active reservation has not
        happened yet and a cancelled one never will. Note this means a
        just-passed reservation is not decidable until the lifecycle job has
        run (:00/:30); winning the claim is the only reliable signal, and a
        lost claim does not say which of the two conditions failed. Read the
        row separately if you need to tell the caller why.
        """
        stmt = (
            update(Reservation)
            .where(
                Reservation.id == reservation_id,
                Reservation.status == ReservationStatus.COMPLETED,
                Reservation.attendance_status.is_(None),
            )
            .values(
                attendance_status=attendance_status,
                attendance_score_delta=score_delta,
                attendance_reason=reason,
                attendance_marked_by=marked_by,
                attendance_marked_at=marked_at,
            )
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

        Counts everything on the day except CANCELLED — deliberately not
        ACTIVE-only. The lifecycle job flips a reservation to COMPLETED once
        its slot has passed, so an ACTIVE-only count would quietly return the
        day's allowance a few minutes after each session and let the user book
        again. Whether the cap held would then depend on when a background job
        last ran, which is not a rule anyone can reason about. Today the
        shipped cutoff hides that (same-day booking closes at 12:00, sessions
        start at 16:00) but both of those are admin-editable.

        CANCELLED stays out: cancelling already costs the user their +1, so it
        has to genuinely free the day. This mirrors ``uq_reservations_slot_active``,
        which lets a cancelled row's slot be re-booked for the same reason.
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
                Reservation.status != ReservationStatus.CANCELLED,
                ReservationSlot.slot_datetime >= day_start,
                ReservationSlot.slot_datetime < day_end,
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def has_reservation_at_time(
        self, user_id: uuid.UUID, slot_datetime: datetime
    ) -> bool:
        """Whether the user already holds a reservation starting at this instant.

        Compares ``slot_datetime`` exactly, not by hour. Slots are generated
        SLOT_DURATION_MINUTES apart and do not overlap, so two of a user's
        reservations collide only when they name the same instant — 16:00 and
        16:30 are two different sessions and must both stay bookable.

        The comparison is against an aware datetime read back from a slot row,
        so the ``timestamptz`` equality is between two instants and no timezone
        reasoning is involved; this is the one query on this model that needs
        none.

        Same status rule as :meth:`count_reservations_on_date`, and for the same
        reasons: everything but CANCELLED. A COMPLETED reservation means the
        user attended that time, and a cancelled one genuinely frees it.

        Returns a bool rather than a count: the cap here is structurally one, so
        there is no number worth reporting and ``LIMIT 1`` is enough work.
        """
        stmt = (
            select(Reservation.id)
            .join(Reservation.slot)
            .where(
                Reservation.user_id == user_id,
                Reservation.status != ReservationStatus.CANCELLED,
                ReservationSlot.slot_datetime == slot_datetime,
            )
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first() is not None

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
        attendance: str | None = None,
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

        if attendance == "pending":
            # The queue: sessions that ran and still have no decision. The
            # completed condition is part of the meaning, not a convenience —
            # nothing else is decidable — so `attendance=pending&status=active`
            # returning nothing is the right answer, not a bug. The legacy flag
            # is excluded because those rows are already scored and the
            # attendance endpoint refuses them; listing them as pending work
            # would hand the admin a row no button can action.
            filters.append(Reservation.status == ReservationStatus.COMPLETED)
            filters.append(Reservation.attendance_status.is_(None))
            filters.append(not_legacy_no_show_sql())
        elif attendance == "decided":
            filters.append(Reservation.attendance_status.is_not(None))
        elif attendance == "attended":
            filters.append(
                Reservation.attendance_status == AttendanceStatus.ATTENDED.value
            )
        elif attendance == "absent":
            # Includes the legacy penalty: an admin looking for missed sessions
            # wants the historical ones too.
            filters.append(absent_sql())

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
        attendance: str | None = None,
        page: int = 1,
        page_size: int = 100,
    ) -> tuple[list[Reservation], int]:
        filters = self._build_admin_filters(
            date_single, date_from, date_to, channel_id, status, search, attendance
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
        """Count reservations by status for the given filters (status filter excluded).

        The attendance filter is excluded for the same reason as the status
        filter: these counts are the totals the filter buttons are pressed
        *against*, so narrowing them by the current selection would make every
        card agree with itself and tell the admin nothing.
        """
        filters = self._build_admin_filters(
            date_single, date_from, date_to, channel_id, None, search
        )

        stmt = (
            select(
                Reservation.status,
                Reservation.notes,
                Reservation.attendance_status,
            )
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
        absent = sum(1 for r in rows if was_absent(r.attendance_status, r.notes))
        attended = sum(
            1
            for r in rows
            if r.attendance_status == AttendanceStatus.ATTENDED.value
        )
        # The work queue, and the reason this count exists: a completed session
        # nobody has judged yet. Legacy-flagged rows are already scored, so
        # they are not awaiting anything.
        awaiting = sum(
            1
            for r in rows
            if r.status == ReservationStatus.COMPLETED
            and r.attendance_status is None
            and _parse_notes(r.notes).get("no_show_penalty_applied") is not True
        )

        return {
            "total": total,
            "active": active,
            "completed": completed,
            "cancelled": cancelled,
            # Kept under its original name: the panel, and any script anyone
            # has pointed at this endpoint, reads `no_show`. What it counts has
            # widened from "the legacy penalty was applied" to "recorded as
            # absent by either system" — under the old name it would have
            # frozen the moment automatic scoring was removed.
            "no_show": absent,
            "attended": attended,
            "awaiting_decision": awaiting,
        }

    async def admin_export(
        self,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
        channel_id: uuid.UUID | None = None,
        status: str | None = None,
        attendance: str | None = None,
    ) -> list[Reservation]:
        filters = self._build_admin_filters(
            None, date_from, date_to, channel_id, status, None, attendance
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
