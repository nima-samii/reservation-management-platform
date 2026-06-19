"""Tests for ReservationService.admin_create_reservation — mocked repos, no DB.

Covers the Sprint 2 admin-create contract:
  * the admin path goes through the SAME booking core (`_book`) as user booking
    — no duplicate booking logic, so validation/score behaviour is identical
  * banned users are rejected before any booking happens
  * a missing user raises NotFoundError
  * a booking-rule violation from the core propagates and suppresses the DM
  * exactly one confirmation DM is enqueued on success, out-of-band
"""
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.core.exceptions import (
    DailyLimitError,
    MaxReservationsError,
    NotFoundError,
    SlotUnavailableError,
    UserBannedError,
)
from app.services.reservation import ReservationService


@pytest.fixture
def service():
    svc = ReservationService.__new__(ReservationService)
    svc._user_repo = AsyncMock()
    # _book is the shared booking core; admin-specific logic is tested in isolation
    # by mocking it. Its internals (lock + _perform_booking validation + score) are
    # the same code path user booking uses and are covered by the booking core.
    svc._book = AsyncMock()
    return svc


def _user(is_banned=False):
    return SimpleNamespace(id=uuid.uuid4(), is_banned=is_banned)


@pytest.mark.asyncio
async def test_delegates_to_booking_core_and_enqueues_dm(service):
    user = _user()
    reservation = SimpleNamespace(id=uuid.uuid4())
    service._user_repo.get_by_id = AsyncMock(return_value=user)
    service._book = AsyncMock(return_value=reservation)
    slot_id = uuid.uuid4()

    with patch(
        "app.services.reservation.enqueue_reservation_creation_notification"
    ) as enqueue:
        result = await service.admin_create_reservation(
            user_id=user.id, slot_id=slot_id, actor="admin"
        )

    assert result is reservation
    # Single booking path: admin booking goes through the shared core unchanged.
    service._book.assert_awaited_once_with(user.id, slot_id)
    enqueue.assert_called_once_with(reservation.id)


@pytest.mark.asyncio
async def test_banned_user_is_rejected_before_booking(service):
    user = _user(is_banned=True)
    service._user_repo.get_by_id = AsyncMock(return_value=user)

    with patch(
        "app.services.reservation.enqueue_reservation_creation_notification"
    ) as enqueue:
        with pytest.raises(UserBannedError):
            await service.admin_create_reservation(
                user_id=user.id, slot_id=uuid.uuid4(), actor="admin"
            )

    service._book.assert_not_called()
    enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_missing_user_raises_not_found(service):
    service._user_repo.get_by_id = AsyncMock(return_value=None)

    with pytest.raises(NotFoundError):
        await service.admin_create_reservation(
            user_id=uuid.uuid4(), slot_id=uuid.uuid4(), actor="admin"
        )

    service._book.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [DailyLimitError(), MaxReservationsError(2), SlotUnavailableError()],
)
async def test_booking_rule_violation_propagates_and_suppresses_dm(service, error):
    user = _user()
    service._user_repo.get_by_id = AsyncMock(return_value=user)
    service._book = AsyncMock(side_effect=error)

    with patch(
        "app.services.reservation.enqueue_reservation_creation_notification"
    ) as enqueue:
        with pytest.raises(type(error)):
            await service.admin_create_reservation(
                user_id=user.id, slot_id=uuid.uuid4(), actor="admin"
            )

    # A failed booking never notifies the user.
    enqueue.assert_not_called()
