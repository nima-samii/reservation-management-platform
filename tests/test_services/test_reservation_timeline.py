"""Unit tests for ReservationTimelineService — no DB.

The pure `assemble()` step is exercised with plain objects standing in for the
ORM rows, and `build()` is checked for its not-found contract with mocked repos.
"""
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import NotFoundError
from app.db.models.reservation import AttendanceStatus, ReservationStatus
from app.db.models.score import ScoreTransactionType
from app.services.reservation_timeline import ReservationTimelineService

BASE = datetime(2026, 6, 19, 15, 30, tzinfo=timezone.utc)


def _reservation(**overrides):
    defaults = dict(
        id=uuid.uuid4(),
        created_at=BASE,
        updated_at=BASE,
        status=ReservationStatus.ACTIVE.value,
        cancelled_at=None,
        cancelled_by=None,
        cancellation_reason=None,
        attendance_status=None,
        attendance_marked_by=None,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _score_tx(*, delta, ttype, created_at, reason=None, meta=None):
    return SimpleNamespace(
        score_delta=delta,
        transaction_type=ttype,
        created_at=created_at,
        reason=reason,
        meta=meta,
    )


def _attendance_tx(*, delta, outcome=None, reason="Recorded by admin", meta=None):
    return _score_tx(
        delta=delta,
        ttype=ScoreTransactionType.ATTENDANCE_SCORE.value,
        created_at=BASE + timedelta(days=1),
        reason=reason,
        meta=meta if meta is not None else ({"attendance_status": outcome} if outcome else None),
    )


def _notification(*, reminder_type, sent_at, status="sent"):
    return SimpleNamespace(reminder_type=reminder_type, sent_at=sent_at, status=status)


def _audit(*, action, admin="admin"):
    return SimpleNamespace(action=action, admin_username=admin)


# ── assemble(): individual event types ────────────────────────────────────

def test_created_event_always_present():
    events = ReservationTimelineService.assemble(_reservation(), [], [], [])
    assert len(events) == 1
    assert events[0].type == "reservation_created"
    assert events[0].title == "Reservation Created"
    assert events[0].timestamp == BASE
    assert events[0].metadata["created_by_admin"] is False


def test_created_by_admin_uses_audit_log():
    audit = [_audit(action="reservation_created_by_admin", admin="alice")]
    events = ReservationTimelineService.assemble(_reservation(), [], [], audit)
    created = events[0]
    assert created.title == "Reservation Created by Admin"
    assert created.metadata["created_by_admin"] is True
    assert created.metadata["admin"] == "alice"


def test_score_awarded_event():
    tx = _score_tx(
        delta=1,
        ttype=ScoreTransactionType.RESERVATION_REWARD.value,
        created_at=BASE,
    )
    events = ReservationTimelineService.assemble(_reservation(), [], [tx], [])
    score = [e for e in events if e.type == "score_awarded"]
    assert len(score) == 1
    assert score[0].title == "Score +1 Awarded"
    assert score[0].metadata["delta"] == 1


def test_notification_events_titled_by_type():
    notifs = [
        _notification(reminder_type="pre_session", sent_at=BASE + timedelta(hours=1)),
        _notification(reminder_type="same_day", sent_at=BASE + timedelta(hours=2)),
    ]
    events = ReservationTimelineService.assemble(_reservation(), notifs, [], [])
    titles = [e.title for e in events if e.type == "notification_sent"]
    assert titles == ["Pre-Session Reminder Sent", "Same-Day Reminder Sent"]


def test_failed_notification_titled_failed():
    notifs = [
        _notification(
            reminder_type="same_day", sent_at=BASE + timedelta(hours=1), status="failed"
        )
    ]
    events = ReservationTimelineService.assemble(_reservation(), notifs, [], [])
    n = [e for e in events if e.type == "notification_sent"][0]
    assert n.title == "Same-Day Reminder Failed"
    assert n.metadata["status"] == "failed"


def test_no_show_event_from_penalty_with_admin():
    tx = _score_tx(
        delta=-1,
        ttype=ScoreTransactionType.NO_SHOW_PENALTY.value,
        created_at=BASE + timedelta(days=1),
        reason="No-show penalty applied by admin",
    )
    audit = [_audit(action="no_show_applied", admin="bob")]
    events = ReservationTimelineService.assemble(_reservation(), [], [tx], audit)
    ns = [e for e in events if e.type == "no_show_applied"]
    assert len(ns) == 1
    assert ns[0].title == "No Show Applied"
    assert ns[0].metadata["admin"] == "bob"
    # The penalty must not also surface as a "Score Awarded" entry.
    assert not any(e.type == "score_awarded" for e in events)


def test_cancellation_event_with_reason_and_actor():
    res = _reservation(
        status=ReservationStatus.CANCELLED.value,
        cancelled_at=BASE + timedelta(days=2),
        cancelled_by="admin",
        cancellation_reason="Customer requested change",
    )
    events = ReservationTimelineService.assemble(res, [], [], [])
    cancel = [e for e in events if e.type == "reservation_cancelled"]
    assert len(cancel) == 1
    assert cancel[0].metadata["cancelled_by"] == "admin"
    assert cancel[0].metadata["reason"] == "Customer requested change"


def test_cancellation_without_cancelled_at_falls_back_to_updated_at():
    # User-initiated cancellation: cancelled_at is NULL but status is cancelled.
    res = _reservation(
        status=ReservationStatus.CANCELLED.value,
        cancelled_at=None,
        updated_at=BASE + timedelta(days=3),
    )
    events = ReservationTimelineService.assemble(res, [], [], [])
    cancel = [e for e in events if e.type == "reservation_cancelled"]
    assert len(cancel) == 1
    assert cancel[0].timestamp == BASE + timedelta(days=3)


# ── assemble(): the attendance decision ────────────────────────────────────

class TestAttendanceEvent:
    """The ledger branch used to end at `elif tx.score_delta > 0`, so an
    attendance decision worth 0 or -5 produced no event at all — the timeline
    showed a session that was never judged."""

    @pytest.mark.parametrize(
        "outcome,delta,expected_title",
        [
            (AttendanceStatus.ATTENDED.value, 10, "Attended · Score +10"),
            (AttendanceStatus.ATTENDED.value, 0, "Attended · Score 0"),
            (AttendanceStatus.ATTENDED.value, -5, "Attended · Score -5"),
            (AttendanceStatus.ABSENT.value, 2, "Did Not Attend · Score +2"),
            (AttendanceStatus.ABSENT.value, 0, "Did Not Attend · Score 0"),
        ],
    )
    def test_every_outcome_and_sign_produces_one_event(
        self, outcome, delta, expected_title
    ):
        res = _reservation(attendance_status=outcome)
        events = ReservationTimelineService.assemble(
            res, [], [_attendance_tx(delta=delta)], []
        )
        decisions = [e for e in events if e.type == "attendance_recorded"]
        assert len(decisions) == 1
        assert decisions[0].title == expected_title
        assert decisions[0].metadata["delta"] == delta
        assert decisions[0].metadata["attendance_status"] == outcome

    def test_a_zero_score_decision_is_not_dropped(self):
        """The specific regression: a real decision that moved no points."""
        res = _reservation(attendance_status=AttendanceStatus.ATTENDED.value)
        events = ReservationTimelineService.assemble(
            res, [], [_attendance_tx(delta=0)], []
        )
        assert any(e.type == "attendance_recorded" for e in events)

    def test_the_explanation_is_carried_through(self):
        res = _reservation(attendance_status=AttendanceStatus.ABSENT.value)
        events = ReservationTimelineService.assemble(
            res, [], [_attendance_tx(delta=-3, reason="Did not join the call")], []
        )
        decision = [e for e in events if e.type == "attendance_recorded"][0]
        assert decision.metadata["reason"] == "Did not join the call"

    def test_the_admin_comes_from_the_audit_log(self):
        res = _reservation(attendance_status=AttendanceStatus.ATTENDED.value)
        audit = [_audit(action="attendance_recorded", admin="carol")]
        events = ReservationTimelineService.assemble(
            res, [], [_attendance_tx(delta=1)], audit
        )
        decision = [e for e in events if e.type == "attendance_recorded"][0]
        assert decision.metadata["admin"] == "carol"

    def test_the_admin_falls_back_to_the_reservation_column(self):
        """Audit logs are prunable; the decision's own column is not."""
        res = _reservation(
            attendance_status=AttendanceStatus.ATTENDED.value,
            attendance_marked_by="dave",
        )
        events = ReservationTimelineService.assemble(
            res, [], [_attendance_tx(delta=1)], []
        )
        decision = [e for e in events if e.type == "attendance_recorded"][0]
        assert decision.metadata["admin"] == "dave"

    def test_the_outcome_falls_back_to_the_ledger_meta(self):
        """score_transactions.reservation_id is ON DELETE SET NULL, so a ledger
        row can outlive the columns — the mirror in `meta` is what is left."""
        res = _reservation(attendance_status=None)
        events = ReservationTimelineService.assemble(
            res,
            [],
            [_attendance_tx(delta=4, outcome=AttendanceStatus.ABSENT.value)],
            [],
        )
        decision = [e for e in events if e.type == "attendance_recorded"][0]
        assert decision.title == "Did Not Attend · Score +4"

    def test_an_unreadable_outcome_still_produces_an_event(self):
        """Better a decision with a vague label than a session that looks
        unjudged."""
        events = ReservationTimelineService.assemble(
            _reservation(), [], [_attendance_tx(delta=1)], []
        )
        decision = [e for e in events if e.type == "attendance_recorded"][0]
        assert decision.title == "Attendance Recorded · Score +1"

    def test_an_attendance_decision_is_not_also_a_score_award(self):
        res = _reservation(attendance_status=AttendanceStatus.ATTENDED.value)
        events = ReservationTimelineService.assemble(
            res, [], [_attendance_tx(delta=7)], []
        )
        assert not any(e.type == "score_awarded" for e in events)


def test_a_negative_admin_adjustment_is_no_longer_dropped():
    """Same root cause as the attendance regression: only gains were emitted,
    so a correction applied against a reservation left no trace."""
    tx = _score_tx(
        delta=-4,
        ttype=ScoreTransactionType.ADMIN_ADJUSTMENT.value,
        created_at=BASE + timedelta(hours=2),
        reason="Duplicate award",
    )
    events = ReservationTimelineService.assemble(_reservation(), [], [tx], [])
    adjusted = [e for e in events if e.type == "score_adjusted"]
    assert len(adjusted) == 1
    assert adjusted[0].title == "Score -4 Deducted"
    assert adjusted[0].metadata["reason"] == "Duplicate award"


def test_a_zero_admin_adjustment_reads_as_reviewed():
    tx = _score_tx(
        delta=0,
        ttype=ScoreTransactionType.ADMIN_ADJUSTMENT.value,
        created_at=BASE + timedelta(hours=2),
    )
    events = ReservationTimelineService.assemble(_reservation(), [], [tx], [])
    adjusted = [e for e in events if e.type == "score_adjusted"]
    assert len(adjusted) == 1
    assert adjusted[0].title == "Score Reviewed, Unchanged"


# ── assemble(): ordering ───────────────────────────────────────────────────

def test_events_sorted_chronologically_oldest_first():
    res = _reservation(
        status=ReservationStatus.CANCELLED.value,
        cancelled_at=BASE + timedelta(days=5),
        cancelled_by="admin",
    )
    score = _score_tx(
        delta=1,
        ttype=ScoreTransactionType.RESERVATION_REWARD.value,
        created_at=BASE,
    )
    notif = _notification(reminder_type="same_day", sent_at=BASE + timedelta(days=1))
    events = ReservationTimelineService.assemble(res, [notif], [score], [])
    timestamps = [e.timestamp for e in events]
    assert timestamps == sorted(timestamps)


def test_created_sorts_before_reward_on_equal_timestamp():
    # Reservation + its +1 reward are created in the same transaction.
    score = _score_tx(
        delta=1,
        ttype=ScoreTransactionType.RESERVATION_REWARD.value,
        created_at=BASE,
    )
    events = ReservationTimelineService.assemble(_reservation(), [], [score], [])
    assert events[0].type == "reservation_created"
    assert events[1].type == "score_awarded"


# ── build(): not-found contract ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_build_raises_not_found_for_missing_reservation():
    svc = ReservationTimelineService.__new__(ReservationTimelineService)
    svc._res_repo = AsyncMock()
    svc._res_repo.get_reservation_admin_detail = AsyncMock(return_value=None)
    svc._notif_repo = AsyncMock()
    svc._score_repo = AsyncMock()
    svc._audit_repo = AsyncMock()

    with pytest.raises(NotFoundError):
        await svc.build(uuid.uuid4())


@pytest.mark.asyncio
async def test_build_assembles_from_all_sources():
    res = _reservation()
    score = _score_tx(
        delta=1,
        ttype=ScoreTransactionType.RESERVATION_REWARD.value,
        created_at=BASE,
    )
    svc = ReservationTimelineService.__new__(ReservationTimelineService)
    svc._res_repo = AsyncMock()
    svc._res_repo.get_reservation_admin_detail = AsyncMock(return_value=res)
    svc._notif_repo = AsyncMock()
    svc._notif_repo.get_for_reservation = AsyncMock(return_value=[])
    svc._score_repo = AsyncMock()
    svc._score_repo.get_for_reservation = AsyncMock(return_value=[score])
    svc._audit_repo = AsyncMock()
    svc._audit_repo.get_for_entity = AsyncMock(return_value=[])

    events = await svc.build(res.id)
    types = [e.type for e in events]
    assert types == ["reservation_created", "score_awarded"]
