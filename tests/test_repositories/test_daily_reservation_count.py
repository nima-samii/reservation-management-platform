"""Day-window tests for ReservationRepository.count_reservations_on_date — real PostgreSQL.

The point of these is the *boundary*, and a boundary between timezones cannot be
mocked: it depends on how Postgres stores `timestamptz` and on what asyncpg
hands back (UTC-aware datetimes, always). A mock would only assert the offset
arithmetic we already believe.

Asia/Baghdad is UTC+3 with no DST, so a local day runs from 21:00 UTC the
previous day to 21:00 UTC. That means local 00:00-02:59 sits on the *previous*
UTC date — which is exactly the case the predecessor got wrong: it derived the
window from a slot's UTC datetime with `.replace(hour=0)`, so "day" silently
meant the UTC calendar day.

With the shipped slot schedule (16:00-23:59 local) nothing crosses UTC midnight
and the two definitions coincide, which is why the bug never surfaced. But
SLOT_START_HOUR is admin-editable down to 0. These tests pin the local-day
definition so it cannot regress the moment someone widens the schedule.
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

# Built here rather than imported from the repository module: importing the
# repo's own TZ would make every assertion below agree with the code by
# construction, including when the code is wrong.
TZ = pytz.timezone(settings.TIMEZONE)

# Far future, so nothing here depends on the wall clock. Deliberately mid-June:
# for a timezone that *did* observe DST this is inside the summer offset, so a
# naive `start + 24h` window would be visibly wrong rather than accidentally
# right.
DAY = date(2030, 6, 15)

_codes = itertools.count(1)


def _local(day: date, hh: int, mm: int = 0) -> datetime:
    """A wall-clock time on a local calendar day, as an aware datetime."""
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
        telegram_channel_id=-3_000_000_000 - n,
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
) -> Reservation:
    slot = ReservationSlot(slot_datetime=when, is_booked=True, channel_id=channel.id)
    session.add(slot)
    await session.flush()
    reservation = Reservation(
        user_id=user.id,
        slot_id=slot.id,
        channel_id=channel.id,
        status=status,
    )
    session.add(reservation)
    await session.flush()
    return reservation


# ── the boundary ──────────────────────────────────────────────────────────────


async def test_a_local_day_is_not_a_utc_day(db_session):
    """The regression this phase exists for.

    Three reservations, chosen so that local days and UTC days disagree on all
    three:

        local DAY   00:30  →  UTC DAY-1 21:30   ← same local day, earlier UTC day
        local DAY   23:00  →  UTC DAY   20:00
        local DAY+1 00:30  →  UTC DAY   21:30   ← next local day, same UTC day

    Counting DAY must return the first two and never the third. The old
    UTC-window code returned exactly the opposite pair.
    """
    user = await _make_user(db_session)
    channel = await _make_channel(db_session)

    await _reserve(db_session, user, channel, _local(DAY, 0, 30))
    await _reserve(db_session, user, channel, _local(DAY, 23, 0))
    await _reserve(db_session, user, channel, _local(DAY + timedelta(days=1), 0, 30))
    await db_session.commit()

    repo = ReservationRepository(db_session)

    assert await repo.count_reservations_on_date(user.id, DAY) == 2
    assert await repo.count_reservations_on_date(user.id, DAY + timedelta(days=1)) == 1


async def test_local_midnight_belongs_to_the_day_it_starts(db_session):
    """The half-open bound, pinned from both sides.

    A slot at exactly 00:00 local opens its own day and closes the previous
    one. The old `<= 23:59:59.999999` sentinel left a gap here that nothing
    would have noticed until a slot landed inside it.
    """
    user = await _make_user(db_session)
    channel = await _make_channel(db_session)

    await _reserve(db_session, user, channel, _local(DAY, 0, 0))
    await db_session.commit()

    repo = ReservationRepository(db_session)

    assert await repo.count_reservations_on_date(user.id, DAY) == 1
    assert await repo.count_reservations_on_date(user.id, DAY - timedelta(days=1)) == 0


async def test_adjacent_days_are_counted_independently(db_session):
    """Each day carries its own tally — the limit is per-day, not rolling."""
    user = await _make_user(db_session)
    channel = await _make_channel(db_session)

    await _reserve(db_session, user, channel, _local(DAY - timedelta(days=1), 18))
    await _reserve(db_session, user, channel, _local(DAY, 18))
    await _reserve(db_session, user, channel, _local(DAY, 20))
    await _reserve(db_session, user, channel, _local(DAY + timedelta(days=1), 18))
    await db_session.commit()

    repo = ReservationRepository(db_session)

    assert await repo.count_reservations_on_date(user.id, DAY - timedelta(days=1)) == 1
    assert await repo.count_reservations_on_date(user.id, DAY) == 2
    assert await repo.count_reservations_on_date(user.id, DAY + timedelta(days=1)) == 1


# ── what is and isn't counted ─────────────────────────────────────────────────


async def test_cancelled_reservations_are_not_counted(db_session):
    """Cancelling must genuinely free the day up.

    The user already paid for it with the -1 score rollback, so a cancelled row
    cannot keep occupying their daily allowance.
    """
    user = await _make_user(db_session)
    channel = await _make_channel(db_session)

    await _reserve(
        db_session, user, channel, _local(DAY, 18), status=ReservationStatus.CANCELLED
    )
    await _reserve(db_session, user, channel, _local(DAY, 20))
    await db_session.commit()

    repo = ReservationRepository(db_session)

    assert await repo.count_reservations_on_date(user.id, DAY) == 1


async def test_completed_reservations_still_count(db_session):
    """A session that already happened still used up the day.

    The lifecycle job flips ACTIVE to COMPLETED once the slot has passed, so an
    ACTIVE-only count would hand the allowance back minutes after each session
    — making the cap depend on when a background job last ran. The shipped
    cutoff currently hides that, but both the cutoff and the slot hours are
    admin-editable, so the rule must not lean on them.
    """
    user = await _make_user(db_session)
    channel = await _make_channel(db_session)

    await _reserve(
        db_session, user, channel, _local(DAY, 18), status=ReservationStatus.COMPLETED
    )
    await _reserve(db_session, user, channel, _local(DAY, 20))
    await db_session.commit()

    repo = ReservationRepository(db_session)

    assert await repo.count_reservations_on_date(user.id, DAY) == 2


async def test_expired_reservations_still_count(db_session):
    """EXPIRED is declared but currently unwritten by any code path.

    Pinned anyway: the predicate is "anything but cancelled", so if EXPIRED is
    ever introduced — most plausibly for no-shows — it counts by default. A
    no-show consumed the slot, so that is the behaviour we want; this test is
    here to make the choice deliberate rather than incidental.
    """
    user = await _make_user(db_session)
    channel = await _make_channel(db_session)

    await _reserve(
        db_session, user, channel, _local(DAY, 18), status=ReservationStatus.EXPIRED
    )
    await db_session.commit()

    repo = ReservationRepository(db_session)

    assert await repo.count_reservations_on_date(user.id, DAY) == 1


async def test_another_users_reservations_are_not_counted(db_session):
    """The limit is per user, not per day globally."""
    user = await _make_user(db_session)
    other = await _make_user(db_session)
    channel = await _make_channel(db_session)

    await _reserve(db_session, user, channel, _local(DAY, 18))
    await _reserve(db_session, other, channel, _local(DAY, 20))
    await _reserve(db_session, other, channel, _local(DAY, 21))
    await db_session.commit()

    repo = ReservationRepository(db_session)

    assert await repo.count_reservations_on_date(user.id, DAY) == 1
    assert await repo.count_reservations_on_date(other.id, DAY) == 2


async def test_an_empty_day_counts_zero(db_session):
    """Zero, not None — the caller compares it against a limit."""
    user = await _make_user(db_session)
    await db_session.commit()

    repo = ReservationRepository(db_session)

    assert await repo.count_reservations_on_date(user.id, DAY) == 0
