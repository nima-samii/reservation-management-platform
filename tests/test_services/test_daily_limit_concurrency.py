"""The per-user booking checks under genuine concurrency — real PostgreSQL, two
connections.

Two rules are read-then-write per user: the daily cap (count the day's
reservations, insert if there is room) and the same-instant rule (look for a
reservation at that time, insert if there is none). Both are guarded by the
same thing — the user row locked FOR UPDATE — so both are pinned here.

Nothing in the booking path used to serialise that pair *per user*. The Redis
advisory lock is keyed on the contended slot
(or on user+time under SEQUENTIAL_FILL), so two bookings for two different
slots on the same day take two different keys and never meet; the row locks
taken during resolution are per-slot for the same reason. Two transactions
could therefore both read the same count and both insert against it.

Worse, the Redis lock is released in `_book`'s `finally` while the surrounding
transaction is still open — the commit happens later, in DbSessionMiddleware —
so even a same-key pair is not serialised all the way through the write.

These tests pin the fix: the user row is locked FOR UPDATE before either check
is read, and Postgres holds that lock until COMMIT. They must be run on two
sessions on two connections; a single session cannot express a race, because
the second half would simply see the first half's uncommitted work.
"""
import asyncio
import itertools
import uuid
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
import pytz
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.config import settings
from app.core.exceptions import (
    DailyLimitError,
    DuplicateSlotTimeError,
    SlotUnavailableError,
)
from app.db.base import Base
from app.db.models.channel import Channel
from app.db.models.reservation import Reservation
from app.db.models.slot import ReservationSlot
from app.db.models.user import User
from app.services.reservation import ReservationService

pytestmark = pytest.mark.asyncio

TZ = pytz.timezone(settings.TIMEZONE)

# Long enough that the loser has certainly reached the lock and blocked, short
# enough not to pad the suite. Only the *unfixed* code depends on this being
# generous: with the lock in place, a sleep that fires too early merely means
# the second booking runs after the first committed, which rejects for the same
# reason by a less interesting route.
_CONTENTION_WINDOW = 0.35

_codes = itertools.count(1)


def _unique() -> int:
    """A collision-proof Telegram id that survives a crashed previous run."""
    return uuid.uuid4().int % 1_000_000_000


def _day(offset_days: int = 4):
    """A local calendar day comfortably inside the booking window and past the
    same-day cutoff rules."""
    return (datetime.now(TZ) + timedelta(days=offset_days)).date()


def _at(day, hour: int) -> datetime:
    return TZ.localize(datetime(day.year, day.month, day.day, hour, 0, 0))


@pytest_asyncio.fixture
async def engine(test_database: str):
    eng = create_async_engine(test_database, echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield eng
    finally:
        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await eng.dispose()


@pytest_asyncio.fixture
async def sessions(engine):
    """Factory for independent sessions, all rolled back at teardown.

    Teardown order matters: a session still holding a row lock would block the
    engine fixture's DROP TABLE.
    """
    factory = async_sessionmaker(engine, expire_on_commit=False)
    opened = []

    def _open():
        session = factory()
        opened.append(session)
        return session

    try:
        yield _open
    finally:
        for session in opened:
            await session.rollback()
            await session.close()


@pytest.fixture
def redis():
    """One in-memory Redis shared by every service in a test.

    Shared on purpose: an advisory lock only means anything across bookers, so
    a per-service fake would quietly make it untestable.
    """
    held: set[str] = set()
    client = MagicMock()

    async def set_nx(key, value, ttl=None):
        if key in held:
            return False
        held.add(key)
        return True

    async def delete(key):
        held.discard(key)

    client.set_nx = AsyncMock(side_effect=set_nx)
    client.delete = AsyncMock(side_effect=delete)
    return client


async def _make_user(session) -> User:
    n = _unique()
    user = User(
        telegram_id=n,
        public_user_code=f"{next(_codes):06d}",
        full_name=f"User {n}",
    )
    session.add(user)
    await session.commit()
    return user


async def _make_channel(session) -> Channel:
    n = _unique()
    channel = Channel(
        name=f"Channel #{n}",
        telegram_channel_id=-4_000_000_000 - n,
        capacity=100,
        priority=0,
        is_active=True,
    )
    session.add(channel)
    await session.commit()
    return channel


async def _make_slots(session, channel: Channel, when: list[datetime]) -> list[uuid.UUID]:
    slots = [ReservationSlot(slot_datetime=dt, is_booked=False, channel_id=channel.id)
             for dt in when]
    session.add_all(slots)
    await session.commit()
    return [s.id for s in slots]


async def _book(session, redis, user: User, slot_id: uuid.UUID):
    with patch("app.services.reservation.enqueue_score_notification"), patch(
        "app.services.reservation.enqueue_reservation_creation_notification"
    ):
        return await ReservationService(session, redis).book_slot(
            telegram_id=user.telegram_id, slot_ref=slot_id
        )


async def _admin_book(session, redis, user: User, slot_id: uuid.UUID):
    with patch("app.services.reservation.enqueue_score_notification"), patch(
        "app.services.reservation.enqueue_reservation_creation_notification"
    ):
        return await ReservationService(session, redis).admin_create_reservation(
            user_id=user.id, slot_id=slot_id, actor="admin"
        )


async def _count_reservations(session, user: User) -> int:
    result = await session.execute(
        select(func.count(Reservation.id)).where(Reservation.user_id == user.id)
    )
    return result.scalar() or 0


# ── the race the fix exists for ───────────────────────────────────────────────


async def test_two_concurrent_bookings_on_one_day_cannot_both_win(sessions, redis):
    """Two slots, one day, one user, two connections — exactly one booking.

    Without the user row lock both transactions read a count of 0 (neither has
    committed) and both insert, leaving the user with two reservations on a day
    that allows one. This is the test that fails before the fix.
    """
    setup = sessions()
    user = await _make_user(setup)
    channel = await _make_channel(setup)
    day = _day()
    slot_a, slot_b = await _make_slots(setup, channel, [_at(day, 18), _at(day, 20)])

    first, second = sessions(), sessions()

    # `first` has booked but NOT committed — it still holds the user row lock.
    await _book(first, redis, user, slot_a)

    # `second` must block here rather than read a stale count.
    racer = asyncio.create_task(_book(second, redis, user, slot_b))
    await asyncio.sleep(_CONTENTION_WINDOW)

    await first.commit()

    with pytest.raises(DailyLimitError):
        await racer

    assert await _count_reservations(setup, user) == 1


async def test_an_admin_booking_racing_a_user_booking_cannot_exceed_the_day(
    sessions, redis
):
    """The two entry points contend with each other, not just with themselves.

    Admin creation goes through the same `_book` → `_perform_booking` core, so
    the lock has to cover it — an admin filling a slot while the user books
    another must not sidestep the day's allowance.
    """
    setup = sessions()
    user = await _make_user(setup)
    channel = await _make_channel(setup)
    day = _day()
    slot_a, slot_b = await _make_slots(setup, channel, [_at(day, 18), _at(day, 20)])

    by_user, by_admin = sessions(), sessions()

    await _book(by_user, redis, user, slot_a)

    racer = asyncio.create_task(_admin_book(by_admin, redis, user, slot_b))
    await asyncio.sleep(_CONTENTION_WINDOW)

    await by_user.commit()

    with pytest.raises(DailyLimitError):
        await racer

    assert await _count_reservations(setup, user) == 1


# ── the lock must not over-reject or over-serialise ───────────────────────────


async def test_bookings_on_different_days_both_succeed(sessions, redis):
    """The lock serialises the check; it must not turn it into a global cap.

    Two bookings by one user on two different days contend for the same user
    row, so the second waits — and must then be allowed through, because its
    own day is still empty.
    """
    setup = sessions()
    user = await _make_user(setup)
    channel = await _make_channel(setup)
    today, tomorrow = _day(4), _day(5)
    slot_a, slot_b = await _make_slots(
        setup, channel, [_at(today, 18), _at(tomorrow, 18)]
    )

    first, second = sessions(), sessions()

    await _book(first, redis, user, slot_a)

    racer = asyncio.create_task(_book(second, redis, user, slot_b))
    await asyncio.sleep(_CONTENTION_WINDOW)

    await first.commit()

    reservation = await racer
    await second.commit()

    assert reservation is not None
    assert await _count_reservations(setup, user) == 2


async def test_two_users_racing_for_one_slot_still_resolve_without_deadlock(
    sessions, redis
):
    """Different users take different user locks, so the pre-existing same-slot
    race is unchanged: one wins, the other is told the slot is gone.

    The lock order is user → slot everywhere, so there is no cycle for two
    bookers to deadlock on. A regression that reordered them, or that locked
    something shared, would hang this test rather than fail it.
    """
    setup = sessions()
    user_a = await _make_user(setup)
    user_b = await _make_user(setup)
    channel = await _make_channel(setup)
    day = _day()
    (slot,) = await _make_slots(setup, channel, [_at(day, 18)])

    first, second = sessions(), sessions()

    outcomes = await asyncio.wait_for(
        asyncio.gather(
            _book(first, redis, user_a, slot),
            _book(second, redis, user_b, slot),
            return_exceptions=True,
        ),
        timeout=10,
    )

    booked = [o for o in outcomes if not isinstance(o, Exception)]
    refused = [o for o in outcomes if isinstance(o, SlotUnavailableError)]

    assert len(booked) == 1, f"expected exactly one winner, got {outcomes}"
    assert len(refused) == 1, f"expected exactly one refusal, got {outcomes}"


# ── the same instant on two channels ──────────────────────────────────────────


@pytest.fixture
def roomy_day():
    """Raise the daily cap out of the way, restoring it afterwards.

    The same-instant tests below need a day that allows more than one booking —
    otherwise the daily cap refuses the second attempt first and the rule under
    test is never reached.
    """
    original = settings.MAX_DAILY_RESERVATIONS
    object.__setattr__(settings, "MAX_DAILY_RESERVATIONS", 5)
    yield
    object.__setattr__(settings, "MAX_DAILY_RESERVATIONS", original)


async def test_the_same_instant_on_two_channels_cannot_both_win(
    sessions, redis, roomy_day
):
    """The race the same-instant rule has to survive.

    Two channels means two distinct free rows at 18:00, so the Redis lock keys
    differ and the per-slot row locks never meet — the two bookings only ever
    contend on the user row. Without that lock both read "no reservation at
    18:00" and both insert, and the user ends the day booked into two live
    sessions at once.
    """
    setup = sessions()
    user = await _make_user(setup)
    channel_a = await _make_channel(setup)
    channel_b = await _make_channel(setup)
    day = _day()
    at_18 = _at(day, 18)
    (slot_a,) = await _make_slots(setup, channel_a, [at_18])
    (slot_b,) = await _make_slots(setup, channel_b, [at_18])

    first, second = sessions(), sessions()

    # `first` has booked 18:00 on channel A but NOT committed.
    await _book(first, redis, user, slot_a)

    # `second` goes for 18:00 on channel B and must block on the user row.
    racer = asyncio.create_task(_book(second, redis, user, slot_b))
    await asyncio.sleep(_CONTENTION_WINDOW)

    await first.commit()

    with pytest.raises(DuplicateSlotTimeError):
        await racer

    assert await _count_reservations(setup, user) == 1


async def test_two_different_times_on_two_channels_both_succeed(
    sessions, redis, roomy_day
):
    """The rule must bite on the instant, not on the day or the channel.

    Same user, same day, two channels, but 18:00 and 20:00 — two sessions
    nobody has to be in two places for. With the daily cap out of the way both
    must be allowed through, even though they serialise on the same user row.
    """
    setup = sessions()
    user = await _make_user(setup)
    channel_a = await _make_channel(setup)
    channel_b = await _make_channel(setup)
    day = _day()
    (slot_a,) = await _make_slots(setup, channel_a, [_at(day, 18)])
    (slot_b,) = await _make_slots(setup, channel_b, [_at(day, 20)])

    first, second = sessions(), sessions()

    await _book(first, redis, user, slot_a)

    racer = asyncio.create_task(_book(second, redis, user, slot_b))
    await asyncio.sleep(_CONTENTION_WINDOW)

    await first.commit()

    reservation = await racer
    await second.commit()

    assert reservation is not None
    assert await _count_reservations(setup, user) == 2


async def test_an_admin_booking_cannot_double_book_the_instant_either(
    sessions, redis, roomy_day
):
    """Admin creation shares the booking core, so it shares the rule — an admin
    placing a user into 18:00 on a second channel is the same impossibility as
    the user doing it themselves."""
    setup = sessions()
    user = await _make_user(setup)
    channel_a = await _make_channel(setup)
    channel_b = await _make_channel(setup)
    day = _day()
    at_18 = _at(day, 18)
    (slot_a,) = await _make_slots(setup, channel_a, [at_18])
    (slot_b,) = await _make_slots(setup, channel_b, [at_18])

    by_user, by_admin = sessions(), sessions()

    await _book(by_user, redis, user, slot_a)

    racer = asyncio.create_task(_admin_book(by_admin, redis, user, slot_b))
    await asyncio.sleep(_CONTENTION_WINDOW)

    await by_user.commit()

    with pytest.raises(DuplicateSlotTimeError):
        await racer

    assert await _count_reservations(setup, user) == 1
