"""Tests for ReservationService.admin_cancel_reservation — mocked repos, no DB.

Covers the admin-cancellation contract:
  * active reservation is cancelled and its slot released
  * already-cancelled / completed reservations are rejected
  * the score is not touched at all
  * a cancellation DM is enqueued exactly once
"""
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.core.exceptions import NotFoundError, ReservationNotCancellableError
from app.db.models.reservation import ReservationStatus
from app.services.reservation import ReservationService


def _make_reservation(status=ReservationStatus.ACTIVE, is_booked=True):
    return SimpleNamespace(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        status=status,
        slot=SimpleNamespace(id=uuid.uuid4(), is_booked=is_booked),
        cancelled_by=None,
        cancelled_at=None,
        cancellation_reason=None,
    )


@pytest.fixture
def service():
    svc = ReservationService.__new__(ReservationService)
    svc._res_repo = AsyncMock()
    svc._slot_repo = AsyncMock()
    svc._score_svc = AsyncMock()
    return svc


@pytest.mark.asyncio
async def test_active_reservation_is_cancelled(service):
    res = _make_reservation()
    service._res_repo.get_reservation_admin_detail = AsyncMock(return_value=res)

    with patch(
        "app.services.reservation.enqueue_reservation_cancellation_notification"
    ) as enqueue, patch("app.services.reservation.enqueue_score_notification"):
        result = await service.admin_cancel_reservation(
            res.id, actor="admin", reason="duplicate booking"
        )

    assert result.status == ReservationStatus.CANCELLED
    assert result.cancelled_by == "admin"
    assert result.cancellation_reason == "duplicate booking"
    assert result.cancelled_at is not None
    # The status flip + actor metadata now go through the atomic race guard.
    service._res_repo.transition_active_to_cancelled.assert_awaited_once()
    kwargs = service._res_repo.transition_active_to_cancelled.await_args.kwargs
    assert kwargs["cancelled_by"] == "admin"
    assert kwargs["cancellation_reason"] == "duplicate booking"
    enqueue.assert_called_once_with(res.id, "duplicate booking")


@pytest.mark.asyncio
async def test_lost_cancel_race_releases_nothing_and_sends_nothing(service):
    """If a concurrent cancel (or the lifecycle-completion job) wins the atomic
    transition first, this caller gets rowcount 0 and must not act on a
    cancellation it did not perform — no slot release, no duplicate DM."""
    res = _make_reservation()
    service._res_repo.get_reservation_admin_detail = AsyncMock(return_value=res)
    service._res_repo.transition_active_to_cancelled = AsyncMock(return_value=False)

    with patch(
        "app.services.reservation.enqueue_reservation_cancellation_notification"
    ) as enqueue, patch("app.services.reservation.enqueue_score_notification"):
        with pytest.raises(ReservationNotCancellableError):
            await service.admin_cancel_reservation(res.id, actor="admin", reason="x")

    service._slot_repo.save.assert_not_called()
    enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_cancellation_releases_slot(service):
    res = _make_reservation(is_booked=True)
    service._res_repo.get_reservation_admin_detail = AsyncMock(return_value=res)

    with patch("app.services.reservation.enqueue_reservation_cancellation_notification"), \
            patch("app.services.reservation.enqueue_score_notification"):
        await service.admin_cancel_reservation(res.id, actor="admin")

    assert res.slot.is_booked is False
    service._slot_repo.save.assert_awaited_once_with(res.slot)


@pytest.mark.asyncio
async def test_cancellation_does_not_touch_the_score(service):
    """Cancelling used to deduct 1, rolling back the +1 from booking. Neither
    exists now: participation is an admin decision on a session that actually
    ran, and a cancelled session never ran. Asserted against the whole score
    service, not a named method, so reinstating any of it fails here."""
    res = _make_reservation()
    service._res_repo.get_reservation_admin_detail = AsyncMock(return_value=res)

    with patch("app.services.reservation.enqueue_reservation_cancellation_notification"), \
            patch("app.services.reservation.enqueue_score_notification") as score_dm:
        await service.admin_cancel_reservation(res.id, actor="admin")

    assert service._score_svc.mock_calls == []
    score_dm.assert_not_called()


@pytest.mark.asyncio
async def test_already_cancelled_is_rejected(service):
    res = _make_reservation(status=ReservationStatus.CANCELLED)
    service._res_repo.get_reservation_admin_detail = AsyncMock(return_value=res)

    with patch("app.services.reservation.enqueue_reservation_cancellation_notification") as enqueue:
        with pytest.raises(ReservationNotCancellableError):
            await service.admin_cancel_reservation(res.id, actor="admin")

    service._res_repo.transition_active_to_cancelled.assert_not_called()
    enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_completed_cannot_be_cancelled(service):
    res = _make_reservation(status=ReservationStatus.COMPLETED)
    service._res_repo.get_reservation_admin_detail = AsyncMock(return_value=res)

    with pytest.raises(ReservationNotCancellableError):
        await service.admin_cancel_reservation(res.id, actor="admin")

    service._res_repo.transition_active_to_cancelled.assert_not_called()


@pytest.mark.asyncio
async def test_missing_reservation_raises_not_found(service):
    service._res_repo.get_reservation_admin_detail = AsyncMock(return_value=None)

    with pytest.raises(NotFoundError):
        await service.admin_cancel_reservation(uuid.uuid4(), actor="admin")
