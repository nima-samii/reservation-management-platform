"""Reusable user-segmentation engine.

A single place that turns a declarative ``SegmentFilter`` into SQLAlchemy
conditions. Every consumer — broadcast preview, audience count, recipient
selection, and (future) saved segments / scheduled broadcasts / campaigns /
analytics — builds on these conditions, so filter logic is never duplicated.

The Sprint-1 quick segments (all_users / active_users / users_with_reservations)
are expressed as ``SegmentFilter`` values too (see ``quick_segment_to_filter``),
so they share the exact same engine and stay behaviourally identical.
"""
import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator
from sqlalchemy import ColumnElement, and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.reservation import Reservation, ReservationStatus
from app.db.models.user import User
from app.db.models.user_broadcast import UserBroadcastAudience

_VALID_STATUSES = {s.value for s in ReservationStatus}
_VALID_GENDERS = {"male", "female", "not_say"}
# No-show is stored as a JSON flag inside reservations.notes (a String column):
# json.dumps({... "no_show_penalty_applied": True}) -> '... "no_show_penalty_applied": true ...'
# The flag is only ever written as `true`, so a substring match is reliable.
_NO_SHOW_PATTERN = '%"no_show_penalty_applied": true%'


class ScoreRange(BaseModel):
    min: Optional[int] = None
    max: Optional[int] = None


class SegmentFilter(BaseModel):
    """Declarative audience definition. All fields are optional and AND-combined.

    The first block is exposed in the advanced-segment UI; the second block is
    internal and used only to express the Sprint-1 quick segments as filters.
    """

    # ── Advanced filters (UI-exposed) ──────────────────────────────────────
    score: Optional[ScoreRange] = None
    reservation_statuses: Optional[list[str]] = None
    has_no_show: Optional[bool] = None
    has_username: Optional[bool] = None
    country_ids: Optional[list[uuid.UUID]] = None
    genders: Optional[list[str]] = None
    created_from: Optional[datetime] = None
    created_to: Optional[datetime] = None

    # ── Internal flags (quick-segment compatibility) ───────────────────────
    is_active: Optional[bool] = None
    is_banned: Optional[bool] = None
    has_reservations: Optional[bool] = None

    @field_validator("reservation_statuses")
    @classmethod
    def _validate_statuses(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if v is None:
            return v
        bad = [s for s in v if s not in _VALID_STATUSES]
        if bad:
            raise ValueError(f"invalid reservation_statuses: {bad}")
        return v

    @field_validator("genders")
    @classmethod
    def _validate_genders(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if v is None:
            return v
        bad = [g for g in v if g not in _VALID_GENDERS]
        if bad:
            raise ValueError(f"invalid genders: {bad}")
        return v


# ── Quick-segment ↔ filter mapping ─────────────────────────────────────────

_QUICK_SEGMENTS: dict[str, SegmentFilter] = {
    UserBroadcastAudience.ALL_USERS.value: SegmentFilter(),
    UserBroadcastAudience.ACTIVE_USERS.value: SegmentFilter(is_active=True, is_banned=False),
    UserBroadcastAudience.USERS_WITH_RESERVATIONS.value: SegmentFilter(has_reservations=True),
}


def quick_segment_to_filter(audience_type: str) -> SegmentFilter:
    """Translate a Sprint-1 quick segment into a SegmentFilter.

    Raises ValueError for an unknown audience so callers surface a 4xx rather
    than silently broadcasting to everyone.
    """
    try:
        # deep copy so callers can never mutate the shared template
        return _QUICK_SEGMENTS[audience_type].model_copy(deep=True)
    except KeyError:
        raise ValueError(f"Unknown audience_type: {audience_type}")


def _has_username_condition() -> ColumnElement[bool]:
    return and_(User.username.is_not(None), User.username != "")


class SegmentationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def build_conditions(
        self, f: SegmentFilter, *, exclude_blocked: bool = True
    ) -> list[ColumnElement[bool]]:
        """Translate a filter into a list of WHERE conditions on User.

        EXISTS subqueries are used for reservation-derived filters so the User
        row is never multiplied (no joins → no N+1, no DISTINCT needed).
        """
        c: list[ColumnElement[bool]] = []

        # Broadcast audiences always exclude users who blocked the bot.
        if exclude_blocked:
            c.append(User.bot_blocked.is_(False))

        # ── Status flags (quick-segment internals) ─────────────────────────
        if f.is_active is not None:
            c.append(User.is_active.is_(f.is_active))
        if f.is_banned is not None:
            c.append(User.is_banned.is_(f.is_banned))

        # ── Score range ────────────────────────────────────────────────────
        if f.score is not None:
            if f.score.min is not None:
                c.append(User.participation_score >= f.score.min)
            if f.score.max is not None:
                c.append(User.participation_score <= f.score.max)

        # ── Username presence ──────────────────────────────────────────────
        if f.has_username is not None:
            cond = _has_username_condition()
            c.append(cond if f.has_username else ~cond)

        # ── Country / gender ───────────────────────────────────────────────
        if f.country_ids:
            c.append(User.country_id.in_(f.country_ids))
        if f.genders:
            c.append(User.gender.in_(f.genders))

        # ── Created-date range ─────────────────────────────────────────────
        if f.created_from is not None:
            c.append(User.created_at >= f.created_from)
        if f.created_to is not None:
            c.append(User.created_at <= f.created_to)

        # ── Reservation-derived (EXISTS subqueries) ────────────────────────
        if f.has_reservations is not None:
            sub = exists().where(Reservation.user_id == User.id)
            c.append(sub if f.has_reservations else ~sub)

        if f.reservation_statuses:
            c.append(
                exists().where(
                    Reservation.user_id == User.id,
                    Reservation.status.in_(f.reservation_statuses),
                )
            )

        if f.has_no_show is not None:
            ns = exists().where(
                Reservation.user_id == User.id,
                Reservation.notes.like(_NO_SHOW_PATTERN),
            )
            c.append(ns if f.has_no_show else ~ns)

        return c

    async def count(self, f: SegmentFilter, *, exclude_blocked: bool = True) -> int:
        conds = self.build_conditions(f, exclude_blocked=exclude_blocked)
        stmt = select(func.count(User.id)).where(*conds)
        return (await self.session.execute(stmt)).scalar() or 0

    async def fetch_recipients(
        self, f: SegmentFilter, *, exclude_blocked: bool = True
    ) -> list[tuple[uuid.UUID, int]]:
        conds = self.build_conditions(f, exclude_blocked=exclude_blocked)
        stmt = select(User.id, User.telegram_id).where(*conds)
        rows = (await self.session.execute(stmt)).all()
        return [(row[0], row[1]) for row in rows]

    async def stats(self, f: SegmentFilter, *, exclude_blocked: bool = True) -> dict:
        """Audience statistics computed from the *final filtered* set in a single
        pass (count + username breakdown + average score)."""
        conds = self.build_conditions(f, exclude_blocked=exclude_blocked)
        stmt = select(
            func.count(User.id),
            func.count(User.id).filter(_has_username_condition()),
            func.avg(User.participation_score),
        ).where(*conds)
        row = (await self.session.execute(stmt)).one()
        total = row[0] or 0
        with_username = row[1] or 0
        avg_score = round(float(row[2]), 1) if row[2] is not None else 0.0
        return {
            "count": total,
            "with_username": with_username,
            "without_username": total - with_username,
            "avg_score": avg_score,
        }
