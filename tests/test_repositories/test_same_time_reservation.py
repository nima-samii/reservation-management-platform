"""ReservationRepository.has_reservation_at_time — real PostgreSQL.

The case this exists for is structural rather than arithmetic, so it is worth
stating plainly: slots are unique per ``(slot_datetime, channel_id)``, so one
clock time exists as one row *per channel*. Two channels means two free rows at
18:00, both bookable, both inside the daily cap once that cap is above 1 —
and both the same evening hour, which one person cannot attend twice.

These run against real Postgres because the predicate is an equality on a
``timestamptz`` column, and what that compares is a property of the database
and the driver, not of the ORM expression. In particular a slot stored from a
localized Asia/Baghdad datetime and one stored from the equivalent UTC datetime
are the *same instant* and must match — a mock comparing naive datetimes would
happily say otherwise.
"""
import itertools
import uuid
from datetime import date, datetime, time, timedelta

import pytest
import pytz

from app.core.config import settings
from app.db.models.channel import Channel
from app.db.models.reservation import Reservation, ReservationStatus
from app.db.models.slot import ReservationSlot
from app.db.models.user import User
from app.repositories.reservation import ReservationRepository

pytestmark = pytest.mark.asyncio

TZ = pytz.timezone(settings.TIMEZONE)

# Far future so nothing here depends on the wall clock.
DAY = date(2030, 6, 15)

_codes = itertools.count(100_000)


def _local(day: date, hh: int, mm: int = 0) -> datetime:
    return TZ.localize(datetime.combine(day, time(hh, mm)))


async def _make_user(session) -> User:
    n = uuid.uuid4().int % 1_000_000_000
    user = User(
        telegram_id=n,
        public_user_code=f"{next(_codes):06d}",
        full_name=f"User {n}",
    )
    session.add(user)
    await session.flush()
    return user


async def _make_channel(session) -> Channel:
    n = uuid.uuid4().int % 1_000_000_000
    channel = Channel(
        name=f"Channel #{n}",
        telegram_channel_id=-5_000_000_000 - n,
        capacity=100,
        priority=0,
        is_active=True,
    )
    session.add(channel)
    await session.flush()
    return channel


async def _reserve(
    session,
    user: User,
    channel: Channel,
    when: datetime,
    *,
    status: str = ReservationStatus.ACTIVE,
) -> None:
    slot = ReservationSlot(slot_datetime=when, is_booked=True, channel_id=channel.id)
    session.add(slot)
    await session.flush()
    session.add(
        Reservation(
            user_id=user.id,
            slot_id=slot.id,
            channel_id=channel.id,
            status=status,
        )
    )
    await session.flush()


# ── the case the rule exists for ──────────────────────────────────────────────


async def test_the_same_time_on_another_channel_is_detected(db_session):
    """The whole point: two channels, one clock time, one user.

    Both rows are free and distinct, so nothing else in the booking path
    objects. Only this query can tell that they are the same evening at 18:00.
    """
    user = await _make_user(db_session)
    channel_a = await _make_channel(db_session)
    channel_b = await _make_channel(db_session)

    await _reserve(db_session, user, channel_a, _local(DAY, 18))
    # The competing row on the other channel — created but unbooked, exactly as
    # the booking path would find it.
    db_session.add(
        ReservationSlot(
            slot_datetime=_local(DAY, 18), is_booked=False, channel_id=channel_b.id
        )
    )
    await db_session.commit()

    repo = ReservationRepository(db_session)

    assert await repo.has_reservation_at_time(user.id, _local(DAY, 18)) is True


async def test_an_equal_instant_written_in_utc_still_matches(db_session):
    """Instant equality, not wall-clock-string equality.

    18:00 Asia/Baghdad is 15:00 UTC. The two are one instant, and the query has
    to say so — asyncpg hands every ``timestamptz`` back as UTC-aware, so a
    caller that resolved its slot from a UTC-normalised source must not slip
    through.
    """
    user = await _make_user(db_session)
    channel = await _make_channel(db_session)

    await _reserve(db_session, user, channel, _local(DAY, 18))
    await db_session.commit()

    same_instant_utc = _local(DAY, 18).astimezone(pytz.UTC)
    repo = ReservationRepository(db_session)

    assert await repo.has_reservation_at_time(user.id, same_instant_utc) is True


# ── what must NOT collide ─────────────────────────────────────────────────────


async def test_a_different_half_hour_is_a_different_session(db_session):
    """18:00 and 18:30 are two separate sessions and must both stay bookable.

    Pins the granularity as the exact instant rather than the hour: slots are
    generated SLOT_DURATION_MINUTES apart and do not overlap, so rounding this
    to the hour would refuse bookings the schedule deliberately allows.
    """
    user = await _make_user(db_session)
    channel = await _make_channel(db_session)

    await _reserve(db_session, user, channel, _local(DAY, 18))
    await db_session.commit()

    repo = ReservationRepository(db_session)

    assert await repo.has_reservation_at_time(user.id, _local(DAY, 18, 30)) is False
    assert await repo.has_reservation_at_time(user.id, _local(DAY, 17, 30)) is False


async def test_the_same_clock_time_on_another_day_does_not_collide(db_session):
    """The rule is per instant, not per time-of-day — it never spans days."""
    user = await _make_user(db_session)
    channel = await _make_channel(db_session)

    await _reserve(db_session, user, channel, _local(DAY, 18))
    await db_session.commit()

    repo = ReservationRepository(db_session)

    assert (
        await repo.has_reservation_at_time(
            user.id, _local(DAY + timedelta(days=1), 18)
        )
        is False
    )


async def test_another_users_reservation_does_not_collide(db_session):
    """Two users share the 18:00 session; that is the normal case, not a clash."""
    user = await _make_user(db_session)
    other = await _make_user(db_session)
    channel = await _make_channel(db_session)

    await _reserve(db_session, other, channel, _local(DAY, 18))
    await db_session.commit()

    repo = ReservationRepository(db_session)

    assert await repo.has_reservation_at_time(user.id, _local(DAY, 18)) is False
    assert await repo.has_reservation_at_time(other.id, _local(DAY, 18)) is True


async def test_no_reservations_at_all_is_false(db_session):
    """False, not None — the caller branches on it directly."""
    user = await _make_user(db_session)
    await db_session.commit()

    repo = ReservationRepository(db_session)

    assert await repo.has_reservation_at_time(user.id, _local(DAY, 18)) is False


# ── status rules, mirroring the daily count ───────────────────────────────────


async def test_a_cancelled_reservation_frees_the_time(db_session):
    """Cancelling already costs the user their +1, so it has to genuinely
    release the time — including for re-booking the very same hour on another
    channel. Same rule as count_reservations_on_date."""
    user = await _make_user(db_session)
    channel = await _make_channel(db_session)

    await _reserve(
        db_session, user, channel, _local(DAY, 18), status=ReservationStatus.CANCELLED
    )
    await db_session.commit()

    repo = ReservationRepository(db_session)

    assert await repo.has_reservation_at_time(user.id, _local(DAY, 18)) is False


async def test_a_completed_reservation_still_holds_the_time(db_session):
    """The lifecycle job flips ACTIVE to COMPLETED once the slot has passed. An
    ACTIVE-only predicate would let the user re-book that instant on a second
    channel minutes later — making the rule depend on when a background job last
    ran rather than on anything the user can see."""
    user = await _make_user(db_session)
    channel = await _make_channel(db_session)

    await _reserve(
        db_session, user, channel, _local(DAY, 18), status=ReservationStatus.COMPLETED
    )
    await db_session.commit()

    repo = ReservationRepository(db_session)

    assert await repo.has_reservation_at_time(user.id, _local(DAY, 18)) is True
