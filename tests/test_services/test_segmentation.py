"""DB-backed tests for the Sprint-2 SegmentationService.

Covers every filter independently, combinations, preview statistics, quick
segment mapping, recipient selection, and count↔recipient consistency.

Requires the test Postgres database configured in tests/conftest.py.
"""
import uuid
from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

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
_chan_seq = 0


def _code() -> str:
    global _code_seq
    _code_seq += 1
    return f"{_code_seq:06d}"


def _next_channel_tg() -> int:
    # Unique per call (not per user) so a single user can hold multiple
    # reservations, each needing its own Channel (telegram_channel_id unique).
    global _chan_seq
    _chan_seq += 1
    return -(900000 + _chan_seq)


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


async def _reservation(
    session,
    user,
    *,
    status=ReservationStatus.ACTIVE.value,
    no_show=False,
    attendance=None,
    slot_datetime=None,
):
    """`no_show` writes the retired penalty flag into `notes`; `attendance`
    writes the current column. Both are kept available because a real database
    contains rows of both kinds and the filter has to match either."""
    ch = Channel(name="C", telegram_channel_id=_next_channel_tg(), capacity=50)
    session.add(ch)
    await session.flush()
    slot = ReservationSlot(
        slot_datetime=slot_datetime or datetime(2026, 8, 1, 18, 0, tzinfo=timezone.utc),
        channel_id=ch.id,
    )
    session.add(slot)
    await session.flush()
    notes = '{"no_show_penalty_applied": true}' if no_show else None
    r = Reservation(
        user_id=user.id,
        slot_id=slot.id,
        channel_id=ch.id,
        status=status,
        notes=notes,
        attendance_status=attendance,
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


@pytest.mark.asyncio
async def test_has_no_show_matches_an_attendance_decision_too(db_session):
    """Absences are recorded in the `attendance_status` column now. A filter
    that still read only the legacy `notes` flag would return an empty audience
    forever, silently — the worst failure mode for a broadcast segment."""
    absent = await _user(db_session, tg=30)
    attended = await _user(db_session, tg=31)
    legacy = await _user(db_session, tg=32)
    await _reservation(
        db_session, absent, status=ReservationStatus.COMPLETED.value, attendance="absent"
    )
    await _reservation(
        db_session, attended, status=ReservationStatus.COMPLETED.value, attendance="attended"
    )
    await _reservation(
        db_session, legacy, status=ReservationStatus.COMPLETED.value, no_show=True
    )
    svc = SegmentationService(db_session)

    # Both systems count, and the two never have to be told apart here.
    assert _tgs(await svc.fetch_recipients(SegmentFilter(has_no_show=True))) == {30, 32}
    assert _tgs(await svc.fetch_recipients(SegmentFilter(has_no_show=False))) == {31}


@pytest.mark.asyncio
async def test_an_absence_worth_points_still_counts_as_a_missed_session(db_session):
    """The segment is about who missed a session, not who was penalised for it —
    an admin may record an absence with a positive score."""
    told_us = await _user(db_session, tg=40)
    await _reservation(
        db_session,
        told_us,
        status=ReservationStatus.COMPLETED.value,
        attendance="absent",
    )
    svc = SegmentationService(db_session)

    assert _tgs(await svc.fetch_recipients(SegmentFilter(has_no_show=True))) == {40}


@pytest.mark.asyncio
async def test_an_undecided_reservation_is_not_a_no_show(db_session):
    """NULL is "not judged yet", not "attended" and not "absent". The negation
    has to return it, which a plain NOT over a NULL column would not."""
    undecided = await _user(db_session, tg=50)
    await _reservation(
        db_session, undecided, status=ReservationStatus.COMPLETED.value
    )
    svc = SegmentationService(db_session)

    assert _tgs(await svc.fetch_recipients(SegmentFilter(has_no_show=True))) == set()
    assert _tgs(await svc.fetch_recipients(SegmentFilter(has_no_show=False))) == {50}


# ── Reservation date range ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reservation_date_from(db_session):
    u1 = await _user(db_session, tg=200)
    u2 = await _user(db_session, tg=201)
    await _reservation(db_session, u1, slot_datetime=datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc))
    await _reservation(db_session, u2, slot_datetime=datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc))
    svc = SegmentationService(db_session)

    got = await svc.fetch_recipients(SegmentFilter(reservation_date_from=date(2026, 8, 1)))
    assert _tgs(got) == {200}


@pytest.mark.asyncio
async def test_reservation_date_to(db_session):
    u1 = await _user(db_session, tg=210)
    u2 = await _user(db_session, tg=211)
    await _reservation(db_session, u1, slot_datetime=datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc))
    await _reservation(db_session, u2, slot_datetime=datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc))
    svc = SegmentationService(db_session)

    got = await svc.fetch_recipients(SegmentFilter(reservation_date_to=date(2026, 8, 31)))
    assert _tgs(got) == {210}


@pytest.mark.asyncio
async def test_reservation_date_range(db_session):
    u1 = await _user(db_session, tg=220)  # inside range
    u2 = await _user(db_session, tg=221)  # before range
    u3 = await _user(db_session, tg=222)  # after range
    await _reservation(db_session, u1, slot_datetime=datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc))
    await _reservation(db_session, u2, slot_datetime=datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc))
    await _reservation(db_session, u3, slot_datetime=datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc))
    svc = SegmentationService(db_session)

    got = await svc.fetch_recipients(
        SegmentFilter(reservation_date_from=date(2026, 8, 1), reservation_date_to=date(2026, 8, 31))
    )
    assert _tgs(got) == {220}


@pytest.mark.asyncio
async def test_reservation_date_range_open_ended(db_session):
    """from-only and to-only behave as half-open ranges, independent of each other."""
    u1 = await _user(db_session, tg=230)
    await _reservation(db_session, u1, slot_datetime=datetime(2026, 12, 31, 12, 0, tzinfo=timezone.utc))
    svc = SegmentationService(db_session)

    assert _tgs(await svc.fetch_recipients(SegmentFilter(reservation_date_from=date(2026, 1, 1)))) == {230}
    assert _tgs(await svc.fetch_recipients(SegmentFilter(reservation_date_to=date(2026, 12, 31)))) == {230}
    assert _tgs(await svc.fetch_recipients(SegmentFilter(reservation_date_to=date(2026, 12, 30)))) == set()


@pytest.mark.asyncio
async def test_reservation_date_range_timezone_boundary(db_session):
    """A slot at 2026-07-31 22:00 UTC is 2026-08-01 01:00 in Asia/Baghdad (+3h) —
    it must count as an August 1st reservation despite its UTC date being July 31."""
    u1 = await _user(db_session, tg=240)
    await _reservation(db_session, u1, slot_datetime=datetime(2026, 7, 31, 22, 0, tzinfo=timezone.utc))
    svc = SegmentationService(db_session)

    got = await svc.fetch_recipients(
        SegmentFilter(reservation_date_from=date(2026, 8, 1), reservation_date_to=date(2026, 8, 1))
    )
    assert _tgs(got) == {240}
    # And it must NOT count as July 31st under the same local-day semantics.
    got = await svc.fetch_recipients(
        SegmentFilter(reservation_date_from=date(2026, 7, 31), reservation_date_to=date(2026, 7, 31))
    )
    assert _tgs(got) == set()


def test_invalid_reservation_date_range():
    with pytest.raises(ValidationError):
        SegmentFilter(reservation_date_from=date(2026, 8, 31), reservation_date_to=date(2026, 8, 1))


# ── Reservation filter correlation (same reservation row) ───────────────────
# Regression coverage for the bug where independent EXISTS clauses let each
# reservation-scoped predicate be satisfied by a *different* reservation of
# the same user. All of the following construct a user whose reservations
# each satisfy only ONE predicate in isolation, and assert the combined
# filter correctly finds nobody — only a user with a SINGLE reservation
# satisfying every predicate at once should match.

@pytest.mark.asyncio
async def test_status_and_date_must_match_same_reservation(db_session):
    mismatched = await _user(db_session, tg=250)
    # Completed, but in July (outside the target range).
    await _reservation(
        db_session, mismatched, status=ReservationStatus.COMPLETED.value,
        slot_datetime=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
    )
    # Active (not completed), but in August (inside the target range).
    await _reservation(
        db_session, mismatched, status=ReservationStatus.ACTIVE.value,
        slot_datetime=datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc),
    )

    matched = await _user(db_session, tg=251)
    # A single reservation satisfying both: completed AND in August.
    await _reservation(
        db_session, matched, status=ReservationStatus.COMPLETED.value,
        slot_datetime=datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc),
    )

    svc = SegmentationService(db_session)
    f = SegmentFilter(
        reservation_statuses=["completed"],
        reservation_date_from=date(2026, 8, 1),
        reservation_date_to=date(2026, 8, 31),
    )
    assert _tgs(await svc.fetch_recipients(f)) == {251}


@pytest.mark.asyncio
async def test_no_show_and_date_must_match_same_reservation(db_session):
    mismatched = await _user(db_session, tg=260)
    # No-show, but in July.
    await _reservation(
        db_session, mismatched, no_show=True,
        slot_datetime=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
    )
    # In August, but not a no-show.
    await _reservation(
        db_session, mismatched, no_show=False,
        slot_datetime=datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc),
    )

    matched = await _user(db_session, tg=261)
    await _reservation(
        db_session, matched, no_show=True,
        slot_datetime=datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc),
    )

    svc = SegmentationService(db_session)
    f = SegmentFilter(
        has_no_show=True,
        reservation_date_from=date(2026, 8, 1),
        reservation_date_to=date(2026, 8, 31),
    )
    assert _tgs(await svc.fetch_recipients(f)) == {261}


@pytest.mark.asyncio
async def test_status_no_show_and_date_must_match_same_reservation(db_session):
    """The exact three-way scenario from the design review: status, no-show,
    and date range must all hold on the same reservation, not three different
    reservations belonging to the same user."""
    mismatched = await _user(db_session, tg=270)
    # Completed + no-show, but in March (outside range).
    await _reservation(
        db_session, mismatched, status=ReservationStatus.COMPLETED.value, no_show=True,
        slot_datetime=datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc),
    )
    # In August, but active (not completed) and not a no-show.
    await _reservation(
        db_session, mismatched, status=ReservationStatus.ACTIVE.value, no_show=False,
        slot_datetime=datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc),
    )

    matched = await _user(db_session, tg=271)
    await _reservation(
        db_session, matched, status=ReservationStatus.COMPLETED.value, no_show=True,
        slot_datetime=datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc),
    )

    svc = SegmentationService(db_session)
    f = SegmentFilter(
        reservation_statuses=["completed"],
        has_no_show=True,
        reservation_date_from=date(2026, 8, 1),
        reservation_date_to=date(2026, 8, 31),
    )
    assert _tgs(await svc.fetch_recipients(f)) == {271}
    # count()/stats() must agree with fetch_recipients() (shared build_conditions()).
    assert (await svc.count(f)) == 1
    assert (await svc.stats(f))["count"] == 1


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
