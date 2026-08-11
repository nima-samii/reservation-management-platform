"""Concurrency tests for SlotRepository.lock_next_slot_by_priority — real PostgreSQL.

These deliberately do NOT mock. The whole design of SEQUENTIAL_FILL rests on
what ``FOR UPDATE OF s SKIP LOCKED ... LIMIT 1`` actually does when two
transactions race, and that is a property of the server, not of our code — a
mock would only assert what we already believe. Every test here runs two or
three genuinely concurrent sessions on separate connections.

What is being pinned:

* two bookers at the same time land on *different* channels, in priority order
* the second booker does not block on the first (it would deadlock this test)
* a slot booked and committed by someone else is excluded, not returned stale
* running out of channels returns None rather than a stale or duplicate row
* inactive channels never receive a booking
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models.channel import Channel
from app.db.models.slot import ReservationSlot
from app.repositories.slot import SlotRepository

pytestmark = pytest.mark.asyncio

# Far enough ahead that the "strictly in the future" filter is never the reason
# a test fails.
SLOT_TIME = datetime(2030, 6, 1, 18, 0, tzinfo=timezone.utc)

_seq = 0


def _next() -> int:
    global _seq
    _seq += 1
    return _seq


@pytest_asyncio.fixture
async def engine(test_database: str):
    """A dedicated engine so each test can open several real connections.

    The shared ``db_session`` fixture hands out a single session, which cannot
    express a race: two concurrent bookings must sit on two connections or the
    second one simply sees the first one's uncommitted work.
    """
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

    Teardown order matters: any session still holding a row lock would block
    the fixture's DROP TABLE, so every session is closed before the engine
    fixture runs its teardown.
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


async def _make_channels(session, priorities: list[int], *, active: bool = True):
    """One channel per priority, each with a free slot at SLOT_TIME."""
    channels = []
    for priority in priorities:
        n = _next()
        channel = Channel(
            name=f"Channel P{priority} #{n}",
            telegram_channel_id=-1_000_000_000 - n,
            capacity=100,
            priority=priority,
            is_active=active,
        )
        session.add(channel)
        await session.flush()
        session.add(
            ReservationSlot(
                slot_datetime=SLOT_TIME, is_booked=False, channel_id=channel.id
            )
        )
        channels.append(channel)
    await session.commit()
    return channels


# ── the core race ─────────────────────────────────────────────────────────────


async def test_concurrent_bookers_cascade_down_the_priority_order(sessions):
    """Two simultaneous bookings for the same time must not collide.

    This is the behaviour SEQUENTIAL_FILL is built on. A blocking lock would
    hang here and a NOWAIT lock would raise — SKIP LOCKED lets the second
    booker fall through to the next channel.
    """
    setup = sessions()
    ch_high, ch_low = await _make_channels(setup, [0, 1])

    first, second = sessions(), sessions()

    slot_a = await SlotRepository(first).lock_next_slot_by_priority(SLOT_TIME)
    # `first` still holds the row lock here — nothing has committed.
    slot_b = await SlotRepository(second).lock_next_slot_by_priority(SLOT_TIME)

    assert slot_a is not None and slot_b is not None
    assert slot_a.id != slot_b.id
    # Priority decides who gets what, not arrival order of the second query.
    assert slot_a.channel_id == ch_high.id
    assert slot_b.channel_id == ch_low.id


async def test_running_out_of_channels_returns_none(sessions):
    """A third booker with only two channels gets nothing — never a row that
    someone else is already claiming."""
    setup = sessions()
    await _make_channels(setup, [0, 1])

    first, second, third = sessions(), sessions(), sessions()
    assert await SlotRepository(first).lock_next_slot_by_priority(SLOT_TIME)
    assert await SlotRepository(second).lock_next_slot_by_priority(SLOT_TIME)

    assert await SlotRepository(third).lock_next_slot_by_priority(SLOT_TIME) is None


async def test_committed_booking_is_excluded_not_returned_stale(sessions):
    """The re-check after locking must see a *committed* is_booked flip.

    Postgres re-evaluates the WHERE clause against the updated row version when
    it takes the lock. If it did not, the loser of a race could be handed a row
    that was booked a moment ago and would double-book it.
    """
    setup = sessions()
    ch_high, ch_low = await _make_channels(setup, [0, 1])

    booker = sessions()
    claimed = await SlotRepository(booker).lock_next_slot_by_priority(SLOT_TIME)
    assert claimed.channel_id == ch_high.id
    claimed.is_booked = True
    await booker.commit()

    later = sessions()
    slot = await SlotRepository(later).lock_next_slot_by_priority(SLOT_TIME)

    assert slot is not None
    assert slot.channel_id == ch_low.id


async def test_all_channels_booked_returns_none(sessions):
    setup = sessions()
    await _make_channels(setup, [0, 1])
    repo = SlotRepository(setup)
    for _ in range(2):
        slot = await repo.lock_next_slot_by_priority(SLOT_TIME)
        slot.is_booked = True
    await setup.commit()

    assert await SlotRepository(sessions()).lock_next_slot_by_priority(SLOT_TIME) is None


async def test_inactive_channels_never_receive_a_booking(sessions):
    setup = sessions()
    await _make_channels(setup, [5])  # active, low priority
    await _make_channels(setup, [0], active=False)  # inactive, would win on priority

    slot = await SlotRepository(sessions()).lock_next_slot_by_priority(SLOT_TIME)

    assert slot is not None
    channel = await setup.get(Channel, slot.channel_id)
    assert channel.is_active is True
    assert channel.priority == 5


async def test_equal_priority_resolves_deterministically(sessions):
    """Two channels sharing a priority must still produce a stable order, so
    concurrent bookers cascade instead of both aiming at the same row."""
    setup = sessions()
    await _make_channels(setup, [0, 0])

    first, second = sessions(), sessions()
    slot_a = await SlotRepository(first).lock_next_slot_by_priority(SLOT_TIME)
    slot_b = await SlotRepository(second).lock_next_slot_by_priority(SLOT_TIME)

    assert slot_a.id != slot_b.id
    assert slot_a.id < slot_b.id  # ordered by id as the documented tiebreak


async def test_unknown_time_returns_none(sessions):
    setup = sessions()
    await _make_channels(setup, [0])

    other_time = SLOT_TIME + timedelta(minutes=30)
    assert (
        await SlotRepository(sessions()).lock_next_slot_by_priority(other_time) is None
    )


# ── the listing query ─────────────────────────────────────────────────────────


async def test_distinct_listing_offers_each_time_once(sessions):
    """Three channels, same two times → two rows, not six."""
    setup = sessions()
    channels = await _make_channels(setup, [0, 1, 2])
    later = SLOT_TIME + timedelta(minutes=30)
    for channel in channels:
        setup.add(
            ReservationSlot(slot_datetime=later, is_booked=False, channel_id=channel.id)
        )
    await setup.commit()

    now = SLOT_TIME - timedelta(days=1)
    slots = await SlotRepository(setup).get_distinct_open_slots_for_date(
        SLOT_TIME.date(), now
    )

    assert [s.slot_datetime for s in slots] == [SLOT_TIME, later]
    # The representative is the highest-priority channel that is still free.
    assert all(s.channel_id == channels[0].id for s in slots)


async def test_distinct_listing_falls_through_to_the_next_free_channel(sessions):
    """When the top channel's slot is taken, the time is still offered — the
    representative just moves down the priority order."""
    setup = sessions()
    ch_high, ch_low = await _make_channels(setup, [0, 1])
    repo = SlotRepository(setup)
    taken = await repo.lock_next_slot_by_priority(SLOT_TIME)
    taken.is_booked = True
    await setup.commit()

    now = SLOT_TIME - timedelta(days=1)
    slots = await repo.get_distinct_open_slots_for_date(SLOT_TIME.date(), now)

    assert len(slots) == 1
    assert slots[0].channel_id == ch_low.id


async def test_distinct_listing_hides_a_fully_booked_time(sessions):
    setup = sessions()
    await _make_channels(setup, [0, 1])
    repo = SlotRepository(setup)
    for _ in range(2):
        slot = await repo.lock_next_slot_by_priority(SLOT_TIME)
        slot.is_booked = True
    await setup.commit()

    now = SLOT_TIME - timedelta(days=1)
    assert await repo.get_distinct_open_slots_for_date(SLOT_TIME.date(), now) == []


async def test_distinct_listing_excludes_inactive_channels(sessions):
    setup = sessions()
    await _make_channels(setup, [0], active=False)

    now = SLOT_TIME - timedelta(days=1)
    slots = await SlotRepository(setup).get_distinct_open_slots_for_date(
        SLOT_TIME.date(), now
    )

    assert slots == []


async def test_distinct_listing_excludes_past_times(sessions):
    setup = sessions()
    await _make_channels(setup, [0])

    now = SLOT_TIME + timedelta(minutes=1)
    slots = await SlotRepository(setup).get_distinct_open_slots_for_date(
        SLOT_TIME.date(), now
    )

    assert slots == []
