"""Tests for ReservationService.record_attendance — mocked repos, no DB.

Phases 1-3 of the attendance rework. The contract under test:
  * the outcome and the score are independent — every combination is allowed
  * the atomic claim happens BEFORE the score, and a lost claim scores nothing
  * a decision is immutable — a second one is refused, not applied
  * only completed reservations are decidable
  * the reason is required and is what reaches the ledger

The claim-ordering tests are the point of the file. The endpoint this replaces
reads a JSON flag out of `notes`, applies the penalty, then writes the flag
back, with no lock and no conditional update — so two concurrent requests both
see an unflagged row and both charge the user. Nothing in the old path had a
test; these are what stop the same shape coming back.
"""
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.core.exceptions import (
    AttendanceAlreadyRecordedError,
    AttendanceNotDecidableError,
    LegacyNoShowRecordedError,
    NotFoundError,
    ValidationError,
)
from app.db.models.reservation import AttendanceStatus, ReservationStatus
from app.services.reservation import ATTENDANCE_SCORE_LIMIT, ReservationService


def _make_reservation(
    service,
    status=ReservationStatus.COMPLETED,
    attendance_status=None,
    score=7,
    notes=None,
):
    """Build a reservation and make it the one the mocked repo hands back."""
    res = SimpleNamespace(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        status=status,
        notes=notes,
        user=SimpleNamespace(participation_score=score),
        attendance_status=attendance_status,
        attendance_score_delta=None,
        attendance_reason=None,
        attendance_marked_by=None,
        attendance_marked_at=None,
    )
    service._res_repo.get_reservation_admin_detail = AsyncMock(return_value=res)
    return res


@pytest.fixture
def service():
    svc = ReservationService.__new__(ReservationService)
    svc._res_repo = AsyncMock()
    svc._slot_repo = AsyncMock()
    svc._user_repo = AsyncMock()
    svc._score_svc = AsyncMock()
    svc._session = AsyncMock()
    svc._res_repo.claim_attendance_decision = AsyncMock(return_value=True)
    svc._score_svc.apply_attendance_score = AsyncMock(
        return_value=SimpleNamespace(id=uuid.uuid4(), transaction_type="attendance_score")
    )
    return svc


async def _record(service, res, **overrides):
    kwargs = {
        "attendance_status": AttendanceStatus.ATTENDED,
        "score_delta": 10,
        "reason": "Hosted the session and answered questions",
        "actor": "admin",
    }
    kwargs.update(overrides)
    with patch("app.services.reservation.enqueue_score_notification") as enqueue:
        outcome = await service.record_attendance(res.id, **kwargs)
    return outcome, enqueue


# ── Attendance and score are separate concepts ────────────────────────────────

@pytest.mark.parametrize(
    "attendance_status,delta",
    [
        (AttendanceStatus.ATTENDED, 10),
        (AttendanceStatus.ATTENDED, 0),
        (AttendanceStatus.ATTENDED, -5),
        (AttendanceStatus.ABSENT, 2),
        (AttendanceStatus.ABSENT, 0),
        (AttendanceStatus.ABSENT, -20),
    ],
)
@pytest.mark.asyncio
async def test_any_outcome_pairs_with_any_score(service, attendance_status, delta):
    """The outcome must never constrain the sign of the score.

    This is the whole reason the feature exists — the old flow hardcoded -1 for
    an absence, so "did not attend, but award 2 points for telling us in
    advance" was unrepresentable.
    """
    res = _make_reservation(service)

    _, _ = await _record(
        service, res, attendance_status=attendance_status, score_delta=delta
    )

    claim = service._res_repo.claim_attendance_decision.await_args.kwargs
    assert claim["attendance_status"] == attendance_status.value
    assert claim["score_delta"] == delta
    scored = service._score_svc.apply_attendance_score.await_args.kwargs
    assert scored["delta"] == delta


@pytest.mark.asyncio
async def test_zero_score_still_writes_a_ledger_row(service):
    """"Attended, 0 points" is a decision the user is told about, so it needs
    its audit row like any other. Skipping it would make the one outcome with
    no score also the one with no trace."""
    res = _make_reservation(service)

    _, enqueue = await _record(service, res, score_delta=0)

    service._score_svc.apply_attendance_score.assert_awaited_once()
    assert service._score_svc.apply_attendance_score.await_args.kwargs["delta"] == 0
    enqueue.assert_called_once()


# ── The claim comes first, and a lost claim costs nothing ─────────────────────

@pytest.mark.asyncio
async def test_claim_is_awaited_before_the_score(service):
    """Ordering, not just presence. Scoring first and claiming second is the
    legacy defect: a crash in between charges the user for a decision no later
    request can tell was already made."""
    calls: list[str] = []
    res = _make_reservation(service)

    async def claim(*_args, **_kwargs):
        calls.append("claim")
        return True

    async def score(*_args, **_kwargs):
        calls.append("score")
        return SimpleNamespace(id=uuid.uuid4(), transaction_type="attendance_score")

    service._res_repo.claim_attendance_decision = AsyncMock(side_effect=claim)
    service._score_svc.apply_attendance_score = AsyncMock(side_effect=score)

    await _record(service, res)

    assert calls == ["claim", "score"]


@pytest.mark.asyncio
async def test_lost_claim_applies_no_score_and_sends_nothing(service):
    """Two admins deciding the same reservation at once: only the winner's
    conditional UPDATE sees rowcount 1. The loser must not charge the user a
    second time nor raise a second DM."""
    res = _make_reservation(service)
    service._res_repo.claim_attendance_decision = AsyncMock(return_value=False)

    with patch("app.services.reservation.enqueue_score_notification") as enqueue:
        with pytest.raises(AttendanceAlreadyRecordedError):
            await service.record_attendance(
                res.id,
                attendance_status=AttendanceStatus.ABSENT,
                score_delta=-5,
                reason="Did not join the session",
                actor="admin",
            )

    service._score_svc.apply_attendance_score.assert_not_called()
    enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_a_decided_reservation_is_refused_not_edited(service):
    """Decisions are immutable. A correction is an admin score adjustment on
    the user, which leaves its own ledger row — never an edit here."""
    res = _make_reservation(service, attendance_status=AttendanceStatus.ATTENDED.value)

    with patch("app.services.reservation.enqueue_score_notification") as enqueue:
        with pytest.raises(AttendanceAlreadyRecordedError):
            await service.record_attendance(
                res.id,
                attendance_status=AttendanceStatus.ABSENT,
                score_delta=-5,
                reason="Changed my mind about this one",
                actor="admin",
            )

    service._res_repo.claim_attendance_decision.assert_not_called()
    service._score_svc.apply_attendance_score.assert_not_called()
    enqueue.assert_not_called()


# ── The legacy no-show penalty scored the same session ────────────────────────

@pytest.mark.asyncio
async def test_a_legacy_no_show_penalty_blocks_a_decision(service):
    """Both mechanisms score one session, so allowing both charges the user
    twice for a single absence. The legacy flag is a JSON substring in `notes`
    and always means -1, so there is nothing to merge it into."""
    res = _make_reservation(
        service, notes='{"no_show_penalty_applied": true}'
    )

    with patch("app.services.reservation.enqueue_score_notification") as enqueue:
        with pytest.raises(LegacyNoShowRecordedError):
            await service.record_attendance(
                res.id,
                attendance_status=AttendanceStatus.ABSENT,
                score_delta=-5,
                reason="Did not show up",
                actor="admin",
            )

    service._res_repo.claim_attendance_decision.assert_not_called()
    service._score_svc.apply_attendance_score.assert_not_called()
    enqueue.assert_not_called()


@pytest.mark.parametrize(
    "notes",
    [None, "", "not json at all", "{}", '{"no_show_penalty_applied": false}'],
)
@pytest.mark.asyncio
async def test_notes_without_the_legacy_flag_do_not_block(service, notes):
    """`notes` is a free-text column that happens to carry JSON sometimes, so
    unparseable content must read as "no penalty", not as an error."""
    res = _make_reservation(service, notes=notes)

    outcome, _ = await _record(service, res)

    assert outcome.score_delta == 10
    service._res_repo.claim_attendance_decision.assert_awaited_once()


# ── Only a session that actually ran can be judged ────────────────────────────

@pytest.mark.parametrize(
    "status",
    [ReservationStatus.ACTIVE, ReservationStatus.CANCELLED, ReservationStatus.EXPIRED],
)
@pytest.mark.asyncio
async def test_only_completed_reservations_are_decidable(service, status):
    res = _make_reservation(service, status=status)

    with pytest.raises(AttendanceNotDecidableError) as exc:
        await service.record_attendance(
            res.id,
            attendance_status=AttendanceStatus.ATTENDED,
            score_delta=1,
            reason="Attended the whole session",
            actor="admin",
        )

    # The status is in the message because for a just-passed ACTIVE row it is
    # the only thing that explains the wait for the :00/:30 lifecycle job. It
    # reads as the bare value whether the caller passed an enum member or the
    # raw string the database returns.
    assert f"current status: {status.value})" in exc.value.message
    assert exc.value.current_status == status.value
    service._res_repo.claim_attendance_decision.assert_not_called()
    service._score_svc.apply_attendance_score.assert_not_called()


@pytest.mark.asyncio
async def test_missing_reservation_raises_not_found(service):
    service._res_repo.get_reservation_admin_detail = AsyncMock(return_value=None)

    with pytest.raises(NotFoundError):
        await service.record_attendance(
            uuid.uuid4(),
            attendance_status=AttendanceStatus.ATTENDED,
            score_delta=1,
            reason="Attended the whole session",
            actor="admin",
        )

    service._res_repo.claim_attendance_decision.assert_not_called()


# ── The reason reaches the user, so it is validated ───────────────────────────

@pytest.mark.parametrize("reason", ["", "   ", "\n\t "])
@pytest.mark.asyncio
async def test_a_blank_reason_is_rejected(service, reason):
    res = _make_reservation(service)

    with pytest.raises(ValidationError):
        await service.record_attendance(
            res.id,
            attendance_status=AttendanceStatus.ATTENDED,
            score_delta=5,
            reason=reason,
            actor="admin",
        )

    service._res_repo.claim_attendance_decision.assert_not_called()


@pytest.mark.asyncio
async def test_an_overlong_reason_is_rejected_not_truncated(service):
    """attendance_reason is String(256). Truncating would quote a half sentence
    back to the user; refusing lets the admin shorten it themselves."""
    res = _make_reservation(service)

    with pytest.raises(ValidationError):
        await service.record_attendance(
            res.id,
            attendance_status=AttendanceStatus.ATTENDED,
            score_delta=5,
            reason="x" * 257,
            actor="admin",
        )

    service._res_repo.claim_attendance_decision.assert_not_called()


@pytest.mark.asyncio
async def test_the_reason_is_stripped_before_it_is_stored(service):
    res = _make_reservation(service)

    outcome, _ = await _record(service, res, reason="  Answered every question  ")

    assert outcome.reason == "Answered every question"
    claim = service._res_repo.claim_attendance_decision.await_args.kwargs
    assert claim["reason"] == "Answered every question"
    scored = service._score_svc.apply_attendance_score.await_args.kwargs
    assert scored["reason"] == "Answered every question"


@pytest.mark.parametrize(
    "delta", [ATTENDANCE_SCORE_LIMIT + 1, -ATTENDANCE_SCORE_LIMIT - 1]
)
@pytest.mark.asyncio
async def test_a_score_beyond_the_bound_is_rejected(service, delta):
    res = _make_reservation(service)

    with pytest.raises(ValidationError):
        await service.record_attendance(
            res.id,
            attendance_status=AttendanceStatus.ATTENDED,
            score_delta=delta,
            reason="Ran the session for the whole cohort",
            actor="admin",
        )

    service._res_repo.claim_attendance_decision.assert_not_called()


@pytest.mark.parametrize("delta", [ATTENDANCE_SCORE_LIMIT, -ATTENDANCE_SCORE_LIMIT])
@pytest.mark.asyncio
async def test_the_bound_itself_is_allowed(service, delta):
    res = _make_reservation(service)

    await _record(service, res, score_delta=delta)

    service._score_svc.apply_attendance_score.assert_awaited_once()


# ── What the caller gets back ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_decision_is_mirrored_onto_the_loaded_row(service):
    """The claim is a bulk UPDATE with synchronize_session=False, so the loaded
    instance keeps its pre-claim values unless we mirror them."""
    res = _make_reservation(service)

    outcome, _ = await _record(
        service, res, attendance_status=AttendanceStatus.ABSENT, score_delta=-3
    )

    assert res.attendance_status == AttendanceStatus.ABSENT.value
    assert res.attendance_score_delta == -3
    assert res.attendance_reason == "Hosted the session and answered questions"
    assert res.attendance_marked_by == "admin"
    assert res.attendance_marked_at is not None
    assert outcome.reservation is res
    assert outcome.attendance_status == AttendanceStatus.ABSENT.value
    assert outcome.score_delta == -3


@pytest.mark.asyncio
async def test_the_new_score_is_refreshed_from_the_database(service):
    """apply_score_delta increments in SQL. Adding the delta locally instead
    would report a balance that hides any concurrent adjustment."""
    res = _make_reservation(service, score=7)

    outcome, _ = await _record(service, res, score_delta=10)

    service._session.refresh.assert_awaited_once_with(
        res.user, ["participation_score"]
    )
    # The mocked refresh is a no-op, so this is the value the refresh produced —
    # deliberately not 7 + 10, which is what a local addition would have given.
    assert outcome.new_score == 7


@pytest.mark.asyncio
async def test_the_outcome_is_carried_into_the_ledger_meta(service):
    """The ledger row has to be readable on its own — the notification formats
    from it, and it outlives the reservation row (ON DELETE SET NULL)."""
    res = _make_reservation(service)

    await _record(service, res, attendance_status=AttendanceStatus.ABSENT)

    meta = service._score_svc.apply_attendance_score.await_args.kwargs["meta"]
    assert meta["attendance_status"] == AttendanceStatus.ABSENT.value
    assert meta["admin"] == "admin"


@pytest.mark.asyncio
async def test_the_notification_is_enqueued_once_with_the_new_type(service):
    res = _make_reservation(service)

    _, enqueue = await _record(service, res)

    tx = service._score_svc.apply_attendance_score.return_value
    enqueue.assert_called_once_with(tx.id, "attendance_score")
