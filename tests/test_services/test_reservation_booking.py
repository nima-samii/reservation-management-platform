"""Tests for ReservationService._perform_booking's inactivity-reminder hook —
mocked repos, no DB.

Covers the "Reservation Flow" contract: a successful booking through the
shared core (used by both user and admin entry points) refreshes
`users.last_reservation_at` to the booking's `now`, exactly once.
"""
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.reservation import ReservationService

FIXED_NOW = datetime(2026, 7, 9, 10, 0, tzinfo=timezone.utc)


@pytest.fixture
def service():
    svc = ReservationService.__new__(ReservationService)
    svc._slot_repo = AsyncMock()
    svc._res_repo = AsyncMock()
    svc._user_repo = AsyncMock()
    svc._score_svc = AsyncMock()
    svc._now_tz = lambda: FIXED_NOW
    return svc


def _slot(is_booked=False):
    return SimpleNamespace(
        id=uuid.uuid4(),
        slot_datetime=FIXED_NOW + timedelta(days=2),
        is_booked=is_booked,
        channel_id=uuid.uuid4(),
    )


@pytest.mark.asyncio
async def test_successful_booking_sets_last_reservation_at(service):
    user_id = uuid.uuid4()
    slot = _slot()
    reservation = SimpleNamespace(id=uuid.uuid4())

    service._slot_repo.get_slot_with_lock = AsyncMock(return_value=slot)
    service._res_repo.count_reservations_on_date = AsyncMock(return_value=0)
    service._res_repo.count_active_reservations = AsyncMock(return_value=0)
    service._res_repo.has_reservation_at_time = AsyncMock(return_value=False)
    service._res_repo.create = AsyncMock(return_value=reservation)
    service._res_repo.get_reservation_with_details = AsyncMock(return_value=reservation)

    with patch("app.services.reservation.enqueue_score_notification"):
        result = await service._perform_booking(user_id, slot.id)

    assert result is reservation
    service._user_repo.set_last_reservation_at.assert_awaited_once_with(user_id, FIXED_NOW)


@pytest.mark.asyncio
async def test_booking_does_not_touch_the_score(service):
    """Booking used to award +1. It no longer moves the score at all — showing
    up is what counts, and that is an admin decision on the finished session.
    Asserted against the whole score service so reinstating any of it fails."""
    user_id = uuid.uuid4()
    slot = _slot()
    reservation = SimpleNamespace(id=uuid.uuid4())

    service._slot_repo.get_slot_with_lock = AsyncMock(return_value=slot)
    service._res_repo.count_reservations_on_date = AsyncMock(return_value=0)
    service._res_repo.count_active_reservations = AsyncMock(return_value=0)
    service._res_repo.has_reservation_at_time = AsyncMock(return_value=False)
    service._res_repo.create = AsyncMock(return_value=reservation)
    service._res_repo.get_reservation_with_details = AsyncMock(return_value=reservation)

    with patch("app.services.reservation.enqueue_score_notification") as score_dm:
        await service._perform_booking(user_id, slot.id)

    assert service._score_svc.mock_calls == []
    score_dm.assert_not_called()


@pytest.mark.asyncio
async def test_failed_booking_never_sets_last_reservation_at(service):
    """A slot that's already booked must reject before touching the user row."""
    from app.core.exceptions import SlotUnavailableError

    user_id = uuid.uuid4()
    slot = _slot(is_booked=True)
    service._slot_repo.get_slot_with_lock = AsyncMock(return_value=slot)
    service._res_repo.count_reservations_on_date = AsyncMock(return_value=0)
    service._res_repo.count_active_reservations = AsyncMock(return_value=0)

    with pytest.raises(SlotUnavailableError):
        await service._perform_booking(user_id, slot.id)

    service._user_repo.set_last_reservation_at.assert_not_called()


@pytest.mark.asyncio
async def test_cancellation_does_not_touch_last_reservation_at(service):
    from app.db.models.reservation import ReservationStatus

    reservation = SimpleNamespace(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        status=ReservationStatus.ACTIVE,
        slot=SimpleNamespace(id=uuid.uuid4(), is_booked=True),
        cancelled_by=None,
        cancelled_at=None,
        cancellation_reason=None,
    )
    service._res_repo.get_reservation_admin_detail = AsyncMock(return_value=reservation)

    with patch("app.services.reservation.enqueue_score_notification"), patch(
        "app.services.reservation.enqueue_reservation_cancellation_notification"
    ):
        await service.admin_cancel_reservation(reservation.id, actor="admin")

    service._user_repo.set_last_reservation_at.assert_not_called()
