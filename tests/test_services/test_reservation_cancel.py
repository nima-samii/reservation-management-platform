"""Tests for ReservationService.admin_cancel_reservation — mocked repos, no DB.

Covers the admin-cancellation contract:
  * active reservation is cancelled and its slot released
  * already-cancelled / completed reservations are rejected
  * the booking's +1 reward is rolled back (-1)
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
async def test_lost_cancel_race_does_not_double_rollback(service):
    """If a concurrent cancel (or the lifecycle-completion job) wins the atomic
    transition first, this caller gets rowcount 0 and must NOT roll the score
    back a second time nor enqueue a duplicate DM — the double-deduction bug."""
    res = _make_reservation()
    service._res_repo.get_reservation_admin_detail = AsyncMock(return_value=res)
    service._res_repo.transition_active_to_cancelled = AsyncMock(return_value=False)

    with patch(
        "app.services.reservation.enqueue_reservation_cancellation_notification"
    ) as enqueue, patch("app.services.reservation.enqueue_score_notification"):
        with pytest.raises(ReservationNotCancellableError):
            await service.admin_cancel_reservation(res.id, actor="admin", reason="x")

    service._score_svc.rollback_cancellation.assert_not_called()
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
async def test_booking_reward_is_rolled_back(service):
    res = _make_reservation()
    service._res_repo.get_reservation_admin_detail = AsyncMock(return_value=res)

    with patch("app.services.reservation.enqueue_reservation_cancellation_notification"), \
            patch("app.services.reservation.enqueue_score_notification"):
        await service.admin_cancel_reservation(res.id, actor="admin")

    # The +1 earned at booking is rolled back (-1); no other score side-effects.
    service._score_svc.rollback_cancellation.assert_awaited_once_with(
        res.user_id, res.id
    )
    service._score_svc.apply_no_show_penalty.assert_not_called()
    service._score_svc.apply_admin_adjustment.assert_not_called()


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
