"""DB-backed tests for the Sprint-2 SegmentationService.

Covers every filter independently, combinations, preview statistics, quick
segment mapping, recipient selection, and count↔recipient consistency.

Requires the test Postgres database configured in tests/conftest.py.
"""
import uuid
from datetime import datetime, timezone

import pytest

from app.db.models.channel import Channel
from app.db.models.reservation import Reservation, ReservationStatus
from app.db.models.slot import ReservationSlot
from app.db.models.user import User
from app.services.segmentation import (
    ScoreRange,
    SegmentFilter,
    SegmentationService,
    quick_segment_to_filter,
)

_code_seq = 0


def _code() -> str:
    global _code_seq
    _code_seq += 1
    return f"{_code_seq:06d}"


async def _user(session, *, tg, score=0, username="u", gender="male",
                is_active=True, is_banned=False, bot_blocked=False,
                country_id=None, created_at=None) -> User:
    u = User(
        telegram_id=tg,
        public_user_code=_code(),
        full_name=f"U{tg}",
        username=username,
        gender=gender,
        participation_score=score,
        is_active=is_active,
        is_banned=is_banned,
        bot_blocked=bot_blocked,
        country_id=country_id,
    )
    session.add(u)
    await session.flush()
    if created_at is not None:
        u.created_at = created_at
        await session.flush()
    return u


async def _reservation(session, user, *, status=ReservationStatus.ACTIVE.value, no_show=False):
    ch = Channel(name="C", telegram_channel_id=-(900000 + user.telegram_id), capacity=50)
    session.add(ch)
    await session.flush()
    slot = ReservationSlot(
        slot_datetime=datetime(2026, 8, 1, 18, 0, tzinfo=timezone.utc), channel_id=ch.id
    )
    session.add(slot)
    await session.flush()
    notes = '{"no_show_penalty_applied": true}' if no_show else None
    r = Reservation(
        user_id=user.id, slot_id=slot.id, channel_id=ch.id, status=status, notes=notes
    )
    session.add(r)
    await session.flush()
    return r


def _tgs(recipients) -> set[int]:
    return {tg for _, tg in recipients}


# ── Score filter ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_score_min_max(db_session):
    await _user(db_session, tg=1, score=0)
    await _user(db_session, tg=2, score=5)
    await _user(db_session, tg=3, score=10)
    svc = SegmentationService(db_session)

    assert _tgs(await svc.fetch_recipients(SegmentFilter(score=ScoreRange(min=5)))) == {2, 3}
    assert _tgs(await svc.fetch_recipients(SegmentFilter(score=ScoreRange(max=5)))) == {1, 2}
    assert _tgs(await svc.fetch_recipients(SegmentFilter(score=ScoreRange(min=1, max=9)))) == {2}


# ── Reservation status ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reservation_statuses(db_session):
    u1 = await _user(db_session, tg=10)
    u2 = await _user(db_session, tg=11)
    await _user(db_session, tg=12)  # no reservation
    await _reservation(db_session, u1, status=ReservationStatus.COMPLETED.value)
    await _reservation(db_session, u2, status=ReservationStatus.CANCELLED.value)
    svc = SegmentationService(db_session)

    got = await svc.fetch_recipients(SegmentFilter(reservation_statuses=["completed"]))
    assert _tgs(got) == {10}
    got = await svc.fetch_recipients(SegmentFilter(reservation_statuses=["completed", "cancelled"]))
    assert _tgs(got) == {10, 11}


# ── No-show ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_has_no_show(db_session):
    u1 = await _user(db_session, tg=20)
    u2 = await _user(db_session, tg=21)
    await _reservation(db_session, u1, status=ReservationStatus.COMPLETED.value, no_show=True)
    await _reservation(db_session, u2, status=ReservationStatus.COMPLETED.value, no_show=False)
    svc = SegmentationService(db_session)

    assert _tgs(await svc.fetch_recipients(SegmentFilter(has_no_show=True))) == {20}
    assert _tgs(await svc.fetch_recipients(SegmentFilter(has_no_show=False))) == {21}


# ── Username ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_has_username(db_session):
    await _user(db_session, tg=30, username="alice")
    await _user(db_session, tg=31, username=None)
    await _user(db_session, tg=32, username="")
    svc = SegmentationService(db_session)

    assert _tgs(await svc.fetch_recipients(SegmentFilter(has_username=True))) == {30}
    assert _tgs(await svc.fetch_recipients(SegmentFilter(has_username=False))) == {31, 32}


# ── Country ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_country_ids(db_session):
    from app.db.models.country import Country

    c1 = Country(name="Iraq", code="IQ", flag_emoji=None)
    c2 = Country(name="Iran", code="IR", flag_emoji=None)
    db_session.add_all([c1, c2])
    await db_session.flush()
    await _user(db_session, tg=40, country_id=c1.id)
    await _user(db_session, tg=41, country_id=c2.id)
    await _user(db_session, tg=42, country_id=None)
    svc = SegmentationService(db_session)

    assert _tgs(await svc.fetch_recipients(SegmentFilter(country_ids=[c1.id]))) == {40}
    assert _tgs(await svc.fetch_recipients(SegmentFilter(country_ids=[c1.id, c2.id]))) == {40, 41}


# ── Gender ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_genders(db_session):
    await _user(db_session, tg=50, gender="male")
    await _user(db_session, tg=51, gender="female")
    await _user(db_session, tg=52, gender="not_say")
    svc = SegmentationService(db_session)

    assert _tgs(await svc.fetch_recipients(SegmentFilter(genders=["female", "not_say"]))) == {51, 52}


# ── Created date range ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_created_range(db_session):
    await _user(db_session, tg=60, created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    await _user(db_session, tg=61, created_at=datetime(2026, 6, 1, tzinfo=timezone.utc))
    await _user(db_session, tg=62, created_at=datetime(2026, 12, 1, tzinfo=timezone.utc))
    svc = SegmentationService(db_session)

    got = await svc.fetch_recipients(
        SegmentFilter(
            created_from=datetime(2026, 3, 1, tzinfo=timezone.utc),
            created_to=datetime(2026, 9, 1, tzinfo=timezone.utc),
        )
    )
    assert _tgs(got) == {61}


# ── Combination ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_filter_combination(db_session):
    u1 = await _user(db_session, tg=70, score=8, username="x")
    await _user(db_session, tg=71, score=8, username=None)   # fails username
    await _user(db_session, tg=72, score=1, username="y")    # fails score
    await _reservation(db_session, u1, status=ReservationStatus.COMPLETED.value)
    svc = SegmentationService(db_session)

    f = SegmentFilter(
        score=ScoreRange(min=5),
        has_username=True,
        reservation_statuses=["completed"],
    )
    assert _tgs(await svc.fetch_recipients(f)) == {70}


# ── bot_blocked always excluded ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_blocked_excluded(db_session):
    await _user(db_session, tg=80, score=10)
    await _user(db_session, tg=81, score=10, bot_blocked=True)
    svc = SegmentationService(db_session)
    assert _tgs(await svc.fetch_recipients(SegmentFilter(score=ScoreRange(min=5)))) == {80}


# ── Stats ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stats(db_session):
    await _user(db_session, tg=90, score=2, username="a")
    await _user(db_session, tg=91, score=4, username=None)
    await _user(db_session, tg=92, score=6, username="c")
    svc = SegmentationService(db_session)

    stats = await svc.stats(SegmentFilter())
    assert stats["count"] == 3
    assert stats["with_username"] == 2
    assert stats["without_username"] == 1
    assert stats["avg_score"] == 4.0


@pytest.mark.asyncio
async def test_stats_empty_audience(db_session):
    svc = SegmentationService(db_session)
    stats = await svc.stats(SegmentFilter(score=ScoreRange(min=999)))
    assert stats == {"count": 0, "with_username": 0, "without_username": 0, "avg_score": 0.0}


# ── Quick segment mapping ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_quick_segment_mapping(db_session):
    u1 = await _user(db_session, tg=100, is_active=True, is_banned=False)
    await _user(db_session, tg=101, is_active=False)
    await _user(db_session, tg=102, is_banned=True)
    await _reservation(db_session, u1)
    svc = SegmentationService(db_session)

    all_f = quick_segment_to_filter("all_users")
    active_f = quick_segment_to_filter("active_users")
    res_f = quick_segment_to_filter("users_with_reservations")

    assert (await svc.count(all_f)) == 3
    assert _tgs(await svc.fetch_recipients(active_f)) == {100}
    assert _tgs(await svc.fetch_recipients(res_f)) == {100}


def test_quick_segment_unknown_raises():
    with pytest.raises(ValueError):
        quick_segment_to_filter("nonsense")


# ── count ↔ recipient consistency ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_count_matches_recipients(db_session):
    for i in range(5):
        await _user(db_session, tg=110 + i, score=i, username=None if i % 2 else "u")
    svc = SegmentationService(db_session)

    for f in [
        SegmentFilter(),
        SegmentFilter(score=ScoreRange(min=2)),
        SegmentFilter(has_username=True),
        SegmentFilter(score=ScoreRange(min=1, max=3), has_username=False),
    ]:
        count = await svc.count(f)
        recipients = await svc.fetch_recipients(f)
        stats = await svc.stats(f)
        assert count == len(recipients) == stats["count"]
