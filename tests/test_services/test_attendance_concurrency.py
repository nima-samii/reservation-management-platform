"""The attendance claim under genuine concurrency — real PostgreSQL, two
connections.

An attendance decision applies a score, so it must happen at most once per
reservation no matter how many requests ask for it: two admins working the same
queue, or one admin's double-tapped button. Phase 2 built the guard as a
conditional UPDATE (``status = 'completed' AND attendance_status IS NULL``) but
could only assert it against mocks, which cannot express a race — a mock returns
whatever it was told to, so the SQL could be wrong in either direction and the
tests would still pass.

These run it for real. Two sessions on two connections is the whole point: a
single session would simply see its own uncommitted work and the second half
would refuse for the wrong reason.

What is being pinned:
  * exactly one decision, exactly one ledger row, exactly one score movement
  * the loser is told the decision already exists, and is charged nothing
  * the claim's own WHERE clause holds even when the advisory read is skipped
  * the guard is per-reservation, not a global lock on deciding anything
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
from unittest.mock import MagicMock, patch

from app.core.config import settings
from app.core.exceptions import (
    AttendanceAlreadyRecordedError,
    AttendanceNotDecidableError,
)
from app.db.base import Base
from app.db.models.channel import Channel
from app.db.models.reservation import AttendanceStatus, Reservation, ReservationStatus
from app.db.models.score import ScoreTransaction, ScoreTransactionType
from app.db.models.slot import ReservationSlot
from app.db.models.user import User
from app.repositories.reservation import ReservationRepository
from app.services.reservation import ReservationService

pytestmark = pytest.mark.asyncio

TZ = pytz.timezone(settings.TIMEZONE)

# Long enough for the loser to have reached the row lock and blocked. Only the
# *unfixed* code depends on this being generous: with the conditional UPDATE in
# place, a sleep that fires early merely means the second decision runs after
# the first committed and is refused by a less interesting route.
_CONTENTION_WINDOW = 0.35

_codes = itertools.count(1)


def _unique() -> int:
    """A collision-proof Telegram id that survives a crashed previous run."""
    return uuid.uuid4().int % 1_000_000_000


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


async def _make_reservation(
    session, *, status=ReservationStatus.COMPLETED, notes=None, score=0
):
    """A user with one reservation on a slot that has already passed."""
    n = _unique()
    user = User(
        telegram_id=n,
        public_user_code=f"{next(_codes):06d}",
        full_name=f"User {n}",
        participation_score=score,
    )
    channel = Channel(
        name=f"Channel #{n}",
        telegram_channel_id=-4_000_000_000 - n,
        capacity=100,
        priority=0,
        is_active=True,
    )
    session.add_all([user, channel])
    await session.flush()

    slot = ReservationSlot(
        slot_datetime=datetime.now(TZ) - timedelta(hours=2),
        is_booked=True,
        channel_id=channel.id,
    )
    session.add(slot)
    await session.flush()

    reservation = Reservation(
        user_id=user.id,
        slot_id=slot.id,
        channel_id=channel.id,
        status=status,
        notes=notes,
    )
    session.add(reservation)
    await session.commit()
    return reservation, user


def _service(session) -> ReservationService:
    # Redis is irrelevant here: record_attendance takes no advisory lock — the
    # conditional UPDATE *is* the serialisation point, which is the property
    # under test.
    return ReservationService(session, MagicMock())


async def _record(session, reservation_id, *, outcome, delta, reason="Decision"):
    with patch("app.services.reservation.enqueue_score_notification"):
        return await _service(session).record_attendance(
            reservation_id,
            attendance_status=outcome,
            score_delta=delta,
            reason=reason,
            actor="admin",
        )


async def _ledger(session, user_id) -> list[ScoreTransaction]:
    rows = await session.execute(
        select(ScoreTransaction).where(ScoreTransaction.user_id == user_id)
    )
    return list(rows.scalars().all())


async def _score(session, user_id) -> int:
    return (
        await session.execute(
            select(User.participation_score).where(User.id == user_id)
        )
    ).scalar()


# ── the race the claim exists for ─────────────────────────────────────────────


async def test_two_concurrent_decisions_cannot_both_win(sessions):
    """The test that fails without the conditional UPDATE.

    Both callers read a row with `attendance_status IS NULL` — neither has
    committed — and under a read-then-write both would write a decision and both
    would charge the user. With the claim in place the second UPDATE blocks on
    the row lock, then matches zero rows and is refused.
    """
    setup = sessions()
    reservation, user = await _make_reservation(setup)

    first, second = sessions(), sessions()

    # `first` has claimed but NOT committed — it still holds the row lock.
    await _record(first, reservation.id, outcome=AttendanceStatus.ATTENDED, delta=10)

    # `second` must block here rather than write a second decision.
    racer = asyncio.create_task(
        _record(second, reservation.id, outcome=AttendanceStatus.ABSENT, delta=-5)
    )
    await asyncio.sleep(_CONTENTION_WINDOW)

    await first.commit()

    with pytest.raises(AttendanceAlreadyRecordedError):
        await racer

    # One decision, and it is the winner's.
    row = (
        await setup.execute(
            select(Reservation).where(Reservation.id == reservation.id)
        )
    ).scalar_one()
    await setup.refresh(row)
    assert row.attendance_status == AttendanceStatus.ATTENDED.value
    assert row.attendance_score_delta == 10


async def test_the_loser_is_charged_nothing(sessions):
    """The ordering guarantee: the claim comes first, so a caller that loses it
    never reaches the score. A charge without a decision is exactly the defect
    the legacy no-show endpoint has."""
    setup = sessions()
    reservation, user = await _make_reservation(setup, score=0)

    first, second = sessions(), sessions()

    await _record(first, reservation.id, outcome=AttendanceStatus.ATTENDED, delta=10)
    racer = asyncio.create_task(
        _record(second, reservation.id, outcome=AttendanceStatus.ABSENT, delta=-5)
    )
    await asyncio.sleep(_CONTENTION_WINDOW)
    await first.commit()

    with pytest.raises(AttendanceAlreadyRecordedError):
        await racer
    await second.rollback()

    ledger = await _ledger(setup, user.id)
    assert len(ledger) == 1
    assert ledger[0].score_delta == 10
    assert ledger[0].transaction_type == ScoreTransactionType.ATTENDANCE_SCORE.value
    # Moved by exactly one delta — not 5, not 15.
    assert await _score(setup, user.id) == 10


async def test_a_zero_score_decision_still_blocks_a_second_one(sessions):
    """The guard is `attendance_status IS NULL`, not "a score was applied". A
    decision worth nothing is still a decision, and a second caller must not be
    able to slip a real score in behind it."""
    setup = sessions()
    reservation, user = await _make_reservation(setup)

    first, second = sessions(), sessions()

    await _record(first, reservation.id, outcome=AttendanceStatus.ATTENDED, delta=0)
    racer = asyncio.create_task(
        _record(second, reservation.id, outcome=AttendanceStatus.ATTENDED, delta=50)
    )
    await asyncio.sleep(_CONTENTION_WINDOW)
    await first.commit()

    with pytest.raises(AttendanceAlreadyRecordedError):
        await racer
    await second.rollback()

    assert await _score(setup, user.id) == 0
    ledger = await _ledger(setup, user.id)
    assert [t.score_delta for t in ledger] == [0]


# ── the guard must not over-serialise ─────────────────────────────────────────


async def test_two_different_reservations_can_be_decided_at_once(sessions):
    """Per-reservation, not global. Two admins working the queue in parallel is
    the normal case, and a guard that serialised all decisions would make the
    panel feel broken under exactly the load it is meant for."""
    setup = sessions()
    res_a, user_a = await _make_reservation(setup)
    res_b, user_b = await _make_reservation(setup)

    first, second = sessions(), sessions()

    outcomes = await asyncio.wait_for(
        asyncio.gather(
            _record(first, res_a.id, outcome=AttendanceStatus.ATTENDED, delta=10),
            _record(second, res_b.id, outcome=AttendanceStatus.ABSENT, delta=-5),
            return_exceptions=True,
        ),
        timeout=10,
    )
    await first.commit()
    await second.commit()

    assert not [o for o in outcomes if isinstance(o, Exception)], outcomes
    assert await _score(setup, user_a.id) == 10
    assert await _score(setup, user_b.id) == -5


# ── the claim's WHERE clause, on its own ──────────────────────────────────────


class TestClaimDirectly:
    """The repository method without the service's advisory read in front of
    it. Those checks exist only to produce a good error message; the claim has
    to hold on its own, because the row can change under them."""

    async def test_a_second_claim_wins_nothing_and_changes_nothing(self, sessions):
        session = sessions()
        reservation, _ = await _make_reservation(session)
        repo = ReservationRepository(session)
        marked_at = datetime.now(TZ)

        first = await repo.claim_attendance_decision(
            reservation.id,
            attendance_status=AttendanceStatus.ATTENDED.value,
            score_delta=10,
            reason="First",
            marked_by="alice",
            marked_at=marked_at,
        )
        second = await repo.claim_attendance_decision(
            reservation.id,
            attendance_status=AttendanceStatus.ABSENT.value,
            score_delta=-5,
            reason="Second",
            marked_by="bob",
            marked_at=marked_at,
        )

        assert first is True
        assert second is False

        # Immutable: the loser did not overwrite any of the five columns.
        row = (
            await session.execute(
                select(Reservation).where(Reservation.id == reservation.id)
            )
        ).scalar_one()
        await session.refresh(row)
        assert row.attendance_status == AttendanceStatus.ATTENDED.value
        assert row.attendance_score_delta == 10
        assert row.attendance_reason == "First"
        assert row.attendance_marked_by == "alice"

    @pytest.mark.parametrize(
        "status",
        [
            ReservationStatus.ACTIVE,
            ReservationStatus.CANCELLED,
            ReservationStatus.EXPIRED,
        ],
    )
    async def test_only_a_completed_reservation_can_be_claimed(self, sessions, status):
        """A session that has not run cannot be judged, and one that was
        cancelled never will be. Enforced in the WHERE clause rather than
        trusted to the caller's read."""
        session = sessions()
        reservation, _ = await _make_reservation(session, status=status)
        repo = ReservationRepository(session)

        won = await repo.claim_attendance_decision(
            reservation.id,
            attendance_status=AttendanceStatus.ATTENDED.value,
            score_delta=1,
            reason="Should not land",
            marked_by="alice",
            marked_at=datetime.now(TZ),
        )

        assert won is False

    async def test_a_missing_reservation_is_not_a_win(self, sessions):
        session = sessions()
        repo = ReservationRepository(session)

        won = await repo.claim_attendance_decision(
            uuid.uuid4(),
            attendance_status=AttendanceStatus.ATTENDED.value,
            score_delta=1,
            reason="Nothing to claim",
            marked_by="alice",
            marked_at=datetime.now(TZ),
        )

        assert won is False


# ── the service's advisory checks, against a real row ─────────────────────────


async def test_an_active_reservation_is_refused_with_a_usable_error(sessions):
    """The admin needs to know this one means "wait": a just-passed session
    stays ACTIVE until the lifecycle job promotes it at :00/:30."""
    session = sessions()
    reservation, user = await _make_reservation(
        session, status=ReservationStatus.ACTIVE
    )

    with pytest.raises(AttendanceNotDecidableError):
        await _record(
            session, reservation.id, outcome=AttendanceStatus.ATTENDED, delta=10
        )

    assert await _ledger(session, user.id) == []


async def test_nothing_is_written_when_the_decision_is_refused(sessions):
    """A refusal has to be inert — no ledger row, no score movement, no
    half-written decision."""
    session = sessions()
    reservation, user = await _make_reservation(
        session, status=ReservationStatus.ACTIVE, score=7
    )
    # Read out before the rollback: rollback expires every loaded instance, and
    # touching `user.id` afterwards would be a lazy refresh from sync context.
    user_id = user.id
    reservation_id = reservation.id

    with pytest.raises(AttendanceNotDecidableError):
        await _record(
            session, reservation_id, outcome=AttendanceStatus.ABSENT, delta=-5
        )
    await session.rollback()

    count = (
        await session.execute(
            select(func.count(ScoreTransaction.id)).where(
                ScoreTransaction.user_id == user_id
            )
        )
    ).scalar()
    assert count == 0
    assert await _score(session, user_id) == 7


async def test_the_legacy_penalty_blocks_a_decision_on_the_same_session(sessions):
    """Both mechanisms score the same session, so allowing both would charge
    the user twice for one absence."""
    from app.core.exceptions import LegacyNoShowRecordedError

    session = sessions()
    reservation, user = await _make_reservation(
        session, notes='{"no_show_penalty_applied": true}'
    )

    with pytest.raises(LegacyNoShowRecordedError):
        await _record(
            session, reservation.id, outcome=AttendanceStatus.ABSENT, delta=-5
        )

    assert await _ledger(session, user.id) == []


# ── the decision, end to end through the database ─────────────────────────────


async def test_a_won_decision_writes_all_five_columns_and_one_ledger_row(sessions):
    session = sessions()
    reservation, user = await _make_reservation(session, score=3)

    outcome = await _record(
        session,
        reservation.id,
        outcome=AttendanceStatus.ABSENT,
        delta=2,
        reason="Told us in advance",
    )
    await session.commit()

    row = (
        await session.execute(
            select(Reservation).where(Reservation.id == reservation.id)
        )
    ).scalar_one()
    await session.refresh(row)
    assert row.attendance_status == AttendanceStatus.ABSENT.value
    assert row.attendance_score_delta == 2
    assert row.attendance_reason == "Told us in advance"
    assert row.attendance_marked_by == "admin"
    assert row.attendance_marked_at is not None

    ledger = await _ledger(session, user.id)
    assert len(ledger) == 1
    assert ledger[0].score_delta == 2
    assert ledger[0].reservation_id == reservation.id
    # The outcome is mirrored into the ledger row so it survives the
    # reservation being deleted (reservation_id is ON DELETE SET NULL).
    assert ledger[0].meta["attendance_status"] == AttendanceStatus.ABSENT.value

    # An absence that earned points — the combination the old ±1 model could
    # not express at all.
    assert await _score(session, user.id) == 5
    assert outcome.new_score == 5
