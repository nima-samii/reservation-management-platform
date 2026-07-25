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
from app.db.models.reservation import ReservationStatus
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
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _score_tx(*, delta, ttype, created_at, reason=None):
    return SimpleNamespace(
        score_delta=delta,
        transaction_type=ttype,
        created_at=created_at,
        reason=reason,
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
