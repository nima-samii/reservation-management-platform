"""End-to-end SEQUENTIAL_FILL booking against real PostgreSQL.

The repository tests prove the lock behaves; the strategy unit tests prove the
strategy asks for the right things. This module proves the whole path a user
actually takes — ``ReservationService.book_slot`` with RESERVATION_STRATEGY set
to SEQUENTIAL_FILL — lands two simultaneous bookers on two different channels,
in priority order, with all the shared reservation rules still applied.

Two sessions on two connections, because a race cannot be expressed on one.
"""
import asyncio
import itertools
import uuid
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
import pytz
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.config import (
    RESERVATION_STRATEGY_SEQUENTIAL_FILL,
    RESERVATION_STRATEGY_THRESHOLD_UNLOCK,
    settings,
)
from app.core.exceptions import DailyLimitError, SlotUnavailableError
from app.db.base import Base
from app.db.models.channel import Channel
from app.db.models.slot import ReservationSlot
from app.db.models.user import User
from app.services.reservation import ReservationService
from app.services.slot import SlotService

pytestmark = pytest.mark.asyncio

TZ = pytz.timezone(settings.TIMEZONE)

def _unique() -> int:
    """A collision-proof Telegram id.

    A module counter is not enough here: it restarts at zero every process, so
    a run that crashed with rows still in the table poisons the next one with a
    duplicate telegram id instead of failing on whatever actually broke.
    """
    return uuid.uuid4().int % 1_000_000_000


# users.public_user_code is CHAR(6), too narrow for the id above. A plain
# counter is right for it: unique within the process, and every test drops its
# tables, so it never has to survive a run.
_codes = itertools.count(1)


def _slot_time() -> datetime:
    """A slot four days out at 18:00 local — comfortably past the same-day
    cutoff rules and the max-days-ahead limit alike."""
    target = datetime.now(TZ) + timedelta(days=4)
    return TZ.localize(
        datetime(target.year, target.month, target.day, 18, 0, 0)
    )


@pytest.fixture
def sequential_fill():
    """Switch the live singleton the way the admin panel does, then put it back."""
    before = settings.RESERVATION_STRATEGY
    object.__setattr__(
        settings, "RESERVATION_STRATEGY", RESERVATION_STRATEGY_SEQUENTIAL_FILL
    )
    yield
    object.__setattr__(settings, "RESERVATION_STRATEGY", before)


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

    Shared on purpose: the advisory lock only means anything across bookers, so
    a per-service fake would quietly make the lock untestable and let a wrong
    lock key pass.
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
    client.held = held
    return client


async def _seed(session, priorities: list[int]) -> tuple[list[Channel], datetime]:
    """One channel per priority, each with a free slot at the same time."""
    slot_time = _slot_time()
    channels = []
    for priority in priorities:
        n = _unique()
        channel = Channel(
            name=f"Channel P{priority} #{n}",
            telegram_channel_id=-2_000_000_000 - n,
            capacity=100,
            priority=priority,
            is_active=True,
        )
        session.add(channel)
        await session.flush()
        session.add(
            ReservationSlot(
                slot_datetime=slot_time, is_booked=False, channel_id=channel.id
            )
        )
        channels.append(channel)
    await session.commit()
    return channels, slot_time


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


async def _book(session, redis, user, slot_ref):
    with patch("app.services.reservation.enqueue_score_notification"), patch(
        "app.services.reservation.enqueue_reservation_creation_notification"
    ):
        return await ReservationService(session, redis).book_slot(
            telegram_id=user.telegram_id, slot_ref=slot_ref
        )


async def _tapped_slot_id(session, slot_date) -> uuid.UUID:
    """What the keyboard would offer — the id every user taps for that time."""
    grouped = await SlotService(session).get_available_slots_for_date_grouped(slot_date)
    return grouped["recommended"][0].id


# ── the end-to-end race ───────────────────────────────────────────────────────


async def test_two_simultaneous_bookers_land_on_different_channels(
    sessions, redis, sequential_fill
):
    """The behaviour SEQUENTIAL_FILL exists to provide.

    Genuinely concurrent (``asyncio.gather``), not merely sequential, because
    both guards under test are only live while the two bookings overlap: the
    row lock, and the advisory lock that a slot-id key would make collide.
    """
    setup = sessions()
    (ch_high, ch_low), slot_time = await _seed(setup, [0, 1])
    alice, bob = await _make_user(setup), await _make_user(setup)

    # Both see the same keyboard, so both tap the same representative slot.
    listing = await SlotService(setup).get_available_slots_for_date_grouped(
        slot_time.date()
    )
    assert len(listing["recommended"]) == 1, "one entry per time, not per channel"
    tapped = listing["recommended"][0].id

    session_a, session_b = sessions(), sessions()
    # return_exceptions so a regression *fails* instead of hanging: a bare
    # gather propagates the first error while the other booking is still
    # holding a row lock, and teardown's DROP TABLE then waits on it forever.
    res_a, res_b = await asyncio.gather(
        _book(session_a, redis, alice, tapped),
        _book(session_b, redis, bob, tapped),
        return_exceptions=True,
    )
    assert not isinstance(res_a, Exception), res_a
    assert not isinstance(res_b, Exception), res_b
    await session_a.commit()
    await session_b.commit()

    assert {res_a.channel_id, res_b.channel_id} == {ch_high.id, ch_low.id}
    assert res_a.slot_id != res_b.slot_id


async def test_one_user_double_tapping_gets_a_single_booking(
    sessions, redis, sequential_fill
):
    """The guarantee the old slot-id lock key provided must survive the switch
    to a per-user key: a double-tapped confirm is one booking, not two on two
    channels. Without the advisory lock both would succeed — neither sees the
    other's uncommitted reservation, so the daily-limit check cannot catch it."""
    setup = sessions()
    await _seed(setup, [0, 1])
    user = await _make_user(setup)
    tapped = await _tapped_slot_id(setup, _slot_time().date())

    session_a, session_b = sessions(), sessions()
    results = await asyncio.gather(
        _book(session_a, redis, user, tapped),
        _book(session_b, redis, user, tapped),
        return_exceptions=True,
    )

    booked = [r for r in results if not isinstance(r, Exception)]
    rejected = [r for r in results if isinstance(r, SlotUnavailableError)]
    assert len(booked) == 1
    assert len(rejected) == 1


async def test_third_booker_is_told_the_slot_is_gone(sessions, redis, sequential_fill):
    """Two channels, three bookers: the third gets the same SlotUnavailableError
    the handler already knows how to present."""
    setup = sessions()
    _, slot_time = await _seed(setup, [0, 1])
    users = [await _make_user(setup) for _ in range(3)]
    tapped = await _tapped_slot_id(setup, slot_time.date())

    a, b, c = sessions(), sessions(), sessions()
    await _book(a, redis, users[0], tapped)
    await _book(b, redis, users[1], tapped)

    with pytest.raises(SlotUnavailableError):
        await _book(c, redis, users[2], tapped)


async def test_booked_time_disappears_from_the_listing(sessions, redis, sequential_fill):
    setup = sessions()
    _, slot_time = await _seed(setup, [0])
    user = await _make_user(setup)
    tapped = await _tapped_slot_id(setup, slot_time.date())

    booking = sessions()
    await _book(booking, redis, user, tapped)
    await booking.commit()

    after = await SlotService(setup).get_available_slots_for_date_grouped(
        slot_time.date()
    )
    assert after["recommended"] == []


async def test_the_time_survives_until_every_channel_is_taken(
    sessions, redis, sequential_fill
):
    """One channel full must not hide the time — the point of sequential fill is
    that the next channel picks it up."""
    setup = sessions()
    (ch_high, ch_low), slot_time = await _seed(setup, [0, 1])
    user = await _make_user(setup)
    tapped = await _tapped_slot_id(setup, slot_time.date())

    booking = sessions()
    res = await _book(booking, redis, user, tapped)
    await booking.commit()
    assert res.channel_id == ch_high.id, "the top channel fills first"

    still_offered = (
        await SlotService(setup).get_available_slots_for_date_grouped(slot_time.date())
    )["recommended"]
    assert len(still_offered) == 1
    assert still_offered[0].channel_id == ch_low.id


# ── logical (lslot:HH:MM) references ──────────────────────────────────────────


async def test_booking_by_time_alone_lands_on_the_top_channel(
    sessions, redis, sequential_fill
):
    """No representative row anywhere in the path — the reference the keyboard
    produced is a time, and a time is all the booking needs."""
    setup = sessions()
    (ch_high, _), slot_time = await _seed(setup, [0, 1])
    user = await _make_user(setup)

    booking = sessions()
    res = await _book(booking, redis, user, slot_time)
    await booking.commit()

    assert res.channel_id == ch_high.id


async def test_two_simultaneous_bookers_by_time_land_on_different_channels(
    sessions, redis, sequential_fill
):
    """The same race as the uuid path, through the callback form users will
    actually be served. Worth repeating rather than trusting by analogy: the
    advisory-lock key is built from the reference itself, so a time and a uuid
    are different keys and only one of them has been exercised so far."""
    setup = sessions()
    (ch_high, ch_low), slot_time = await _seed(setup, [0, 1])
    alice, bob = await _make_user(setup), await _make_user(setup)

    session_a, session_b = sessions(), sessions()
    res_a, res_b = await asyncio.gather(
        _book(session_a, redis, alice, slot_time),
        _book(session_b, redis, bob, slot_time),
        return_exceptions=True,
    )
    assert not isinstance(res_a, Exception), res_a
    assert not isinstance(res_b, Exception), res_b
    await session_a.commit()
    await session_b.commit()

    assert {res_a.channel_id, res_b.channel_id} == {ch_high.id, ch_low.id}


async def test_one_user_double_tapping_a_time_gets_a_single_booking(
    sessions, redis, sequential_fill
):
    setup = sessions()
    await _seed(setup, [0, 1])
    user = await _make_user(setup)
    slot_time = _slot_time()

    session_a, session_b = sessions(), sessions()
    results = await asyncio.gather(
        _book(session_a, redis, user, slot_time),
        _book(session_b, redis, user, slot_time),
        return_exceptions=True,
    )

    assert len([r for r in results if not isinstance(r, Exception)]) == 1
    assert len([r for r in results if isinstance(r, SlotUnavailableError)]) == 1


async def test_a_time_with_no_slots_is_unavailable_not_a_crash(
    sessions, redis, sequential_fill
):
    """A keyboard that outlived its slots — regenerated schedule, deleted
    channel. The reference names a time the database knows nothing about."""
    setup = sessions()
    _, slot_time = await _seed(setup, [0])
    user = await _make_user(setup)

    booking = sessions()
    with pytest.raises(SlotUnavailableError):
        await _book(booking, redis, user, slot_time + timedelta(minutes=7))


async def test_a_logical_button_is_refused_after_the_strategy_is_switched_away(
    sessions, redis, sequential_fill
):
    """The genuinely awkward case: the user was offered lslot: buttons, an admin
    switched to THRESHOLD_UNLOCK, and only then did the user tap Confirm. Their
    keyboard cannot be re-rendered, so the booking has to refuse it — and refuse
    it as "unavailable", the one error the handler already recovers from by
    offering another slot."""
    setup = sessions()
    await _seed(setup, [0, 1])
    user = await _make_user(setup)
    slot_time = _slot_time()

    object.__setattr__(
        settings, "RESERVATION_STRATEGY", RESERVATION_STRATEGY_THRESHOLD_UNLOCK
    )

    booking = sessions()
    with pytest.raises(SlotUnavailableError):
        await _book(booking, redis, user, slot_time)


async def test_a_legacy_uuid_button_still_works_after_switching_to_sequential_fill(
    sessions, redis, sequential_fill
):
    """The mirror image, and the reason slot:{uuid} was kept: a keyboard
    rendered under THRESHOLD_UNLOCK names channel 1's row, and after the switch
    that reference must still book — by its time, through the new path."""
    setup = sessions()
    (ch_high, ch_low), slot_time = await _seed(setup, [0, 1])
    user = await _make_user(setup)

    low_slot = (
        await setup.execute(
            ReservationSlot.__table__.select().where(
                ReservationSlot.channel_id == ch_low.id
            )
        )
    ).first()

    booking = sessions()
    res = await _book(booking, redis, user, low_slot.id)
    await booking.commit()

    # Resolved by *time*, so it lands on the priority winner rather than on the
    # channel the stale button happened to name.
    assert res.channel_id == ch_high.id


# ── shared reservation rules are untouched by the strategy ────────────────────


async def test_daily_limit_still_applies(sessions, redis, sequential_fill):
    """A strategy may pick the channel; it may not hand a user two bookings on
    one day just because a second channel was free."""
    setup = sessions()
    _, slot_time = await _seed(setup, [0, 1])
    user = await _make_user(setup)
    tapped = await _tapped_slot_id(setup, slot_time.date())

    first = sessions()
    await _book(first, redis, user, tapped)
    await first.commit()

    second = sessions()
    with pytest.raises(DailyLimitError):
        await _book(second, redis, user, tapped)


async def test_admin_booking_keeps_its_channel_under_sequential_fill(
    sessions, redis, sequential_fill
):
    """The structural guarantee from Phase 2, now exercised with a strategy that
    genuinely would reassign the channel: an admin picking the *low*-priority
    channel must get exactly that, not the priority winner."""
    setup = sessions()
    (ch_high, ch_low), slot_time = await _seed(setup, [0, 1])
    user = await _make_user(setup)

    low_slot = (
        await setup.execute(
            ReservationSlot.__table__.select().where(
                ReservationSlot.channel_id == ch_low.id
            )
        )
    ).first()

    booking = sessions()
    with patch("app.services.reservation.enqueue_score_notification"), patch(
        "app.services.reservation.enqueue_reservation_creation_notification"
    ):
        res = await ReservationService(booking, redis).admin_create_reservation(
            user_id=user.id, slot_id=low_slot.id, actor="admin"
        )
    await booking.commit()

    assert res.channel_id == ch_low.id
    assert res.channel_id != ch_high.id


async def test_threshold_unlock_is_unaffected_by_the_new_code(sessions, redis):
    """No `sequential_fill` fixture: the default strategy must still offer one
    slot *per channel* and book exactly the one that was tapped."""
    assert settings.RESERVATION_STRATEGY == RESERVATION_STRATEGY_THRESHOLD_UNLOCK

    setup = sessions()
    (ch_high, _), slot_time = await _seed(setup, [0, 1])
    user = await _make_user(setup)

    listing = await SlotService(setup).get_available_slots_for_date_grouped(
        slot_time.date()
    )
    # Channel 1 only: nothing has filled, so the next channel stays locked.
    assert len(listing["recommended"]) == 1
    assert listing["more_available"] == []
    tapped = listing["recommended"][0]
    assert tapped.channel_id == ch_high.id

    booking = sessions()
    res = await _book(booking, redis, user, tapped.id)
    await booking.commit()

    assert res.slot_id == tapped.id
    assert res.channel_id == ch_high.id
