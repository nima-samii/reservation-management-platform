"""The one-reservation-per-instant rule at the service layer — mocked repos.

What the query itself matches is settled against real Postgres in
tests/test_repositories/test_same_time_reservation.py, and whether two
concurrent bookings can both slip past it in
tests/test_services/test_duplicate_slot_time_concurrency.py. Left for this
module is the wiring: that the check runs at all, that it is asked about the
*resolved* slot, where it sits relative to the two caps, and what the user is
told.
"""
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import pytz

from app.core.config import settings
from app.core.exceptions import DailyLimitError, DuplicateSlotTimeError, MaxReservationsError
from app.services.reservation import ReservationService

FIXED_NOW = datetime(2026, 7, 9, 10, 0, tzinfo=timezone.utc)
TZ = pytz.timezone(settings.TIMEZONE)

# 16:00 Asia/Baghdad, a few days out — the hour the rule was reported against.
SLOT_AT = TZ.localize(datetime(2026, 7, 12, 16, 0))


@pytest.fixture
def service():
    svc = ReservationService.__new__(ReservationService)
    svc._slot_repo = AsyncMock()
    svc._res_repo = AsyncMock()
    svc._user_repo = AsyncMock()
    svc._score_svc = AsyncMock()
    svc._now_tz = lambda: FIXED_NOW
    return svc


@pytest.fixture
def caps():
    """Hold both caps clear of the way, restoring them afterwards.

    Every test here is about the same-time rule, and with the shipped daily cap
    of 1 a second booking would be refused before the rule was ever consulted —
    which is correct behaviour but tells us nothing about this code.
    """
    original = (settings.MAX_DAILY_RESERVATIONS, settings.MAX_ACTIVE_RESERVATIONS)
    object.__setattr__(settings, "MAX_DAILY_RESERVATIONS", 5)
    object.__setattr__(settings, "MAX_ACTIVE_RESERVATIONS", 50)
    yield
    object.__setattr__(settings, "MAX_DAILY_RESERVATIONS", original[0])
    object.__setattr__(settings, "MAX_ACTIVE_RESERVATIONS", original[1])


def _slot(when: datetime = SLOT_AT):
    return SimpleNamespace(
        id=uuid.uuid4(),
        slot_datetime=when,
        is_booked=False,
        channel_id=uuid.uuid4(),
    )


def _wire(service, slot, *, already_at_that_time: bool, on_day: int = 0, active: int = 0):
    service._slot_repo.get_slot_with_lock = AsyncMock(return_value=slot)
    service._res_repo.count_reservations_on_date = AsyncMock(return_value=on_day)
    service._res_repo.count_active_reservations = AsyncMock(return_value=active)
    service._res_repo.has_reservation_at_time = AsyncMock(
        return_value=already_at_that_time
    )
    reservation = SimpleNamespace(id=uuid.uuid4())
    service._res_repo.create = AsyncMock(return_value=reservation)
    service._res_repo.get_reservation_with_details = AsyncMock(return_value=reservation)
    service._score_svc.award_reservation_reward = AsyncMock(
        return_value=SimpleNamespace(
            id=uuid.uuid4(), transaction_type="reservation_reward"
        )
    )
    return reservation


async def _attempt(service, slot, **kwargs):
    _wire(service, slot, **kwargs)
    with patch("app.services.reservation.enqueue_score_notification"):
        return await service._perform_booking(uuid.uuid4(), slot.id)


# ── the rule ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_second_booking_at_the_same_instant_is_refused(service, caps):
    with pytest.raises(DuplicateSlotTimeError):
        await _attempt(service, _slot(), already_at_that_time=True)


@pytest.mark.asyncio
async def test_a_free_instant_books_normally(service, caps):
    assert await _attempt(service, _slot(), already_at_that_time=False) is not None


@pytest.mark.asyncio
async def test_a_refusal_never_claims_the_slot(service, caps):
    """The refusal must land before the slot is flipped and the row written —
    otherwise a rejected booking would leave the other channel's 16:00 marked
    as taken and unbookable by anyone."""
    slot = _slot()
    with pytest.raises(DuplicateSlotTimeError):
        await _attempt(service, slot, already_at_that_time=True)

    assert slot.is_booked is False
    service._res_repo.create.assert_not_called()
    service._user_repo.set_last_reservation_at.assert_not_called()


@pytest.mark.asyncio
async def test_the_check_is_not_configurable_away(service):
    """No settings key turns this off — being in two places at once is not a
    policy dial. Run with both caps at their shipped defaults and with the day
    otherwise empty, so nothing else could account for the refusal."""
    with pytest.raises(DuplicateSlotTimeError):
        await _attempt(service, _slot(), already_at_that_time=True)


# ── what it is asked about ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_resolved_slot_s_time_is_what_is_checked(service, caps):
    """Guards the seam with the strategies.

    Under SEQUENTIAL_FILL the reference the user tapped is a *time*, and the
    strategy picks whichever channel's row is still free — so the row actually
    being booked is only known after resolution. Checking anything but the
    resolved row's ``slot_datetime`` would ask about a slot nobody is booking.
    """
    slot = _slot()
    user_id = uuid.uuid4()
    _wire(service, slot, already_at_that_time=False)

    with patch("app.services.reservation.enqueue_score_notification"):
        await service._perform_booking(user_id, slot.id)

    passed_user, passed_when = service._res_repo.has_reservation_at_time.await_args.args
    assert passed_user == user_id
    assert passed_when is slot.slot_datetime


# ── ordering against the two caps ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_daily_cap_is_reported_before_the_same_time_rule(service, caps):
    """Both apply, and the user is told about the cap.

    The same-time error ends in "please choose a different time", which is only
    true advice while the day still has room. At the cap it does not, so the
    blanket refusal has to win.
    """
    object.__setattr__(settings, "MAX_DAILY_RESERVATIONS", 2)
    with pytest.raises(DailyLimitError):
        await _attempt(service, _slot(), already_at_that_time=True, on_day=2)


@pytest.mark.asyncio
async def test_the_active_cap_is_reported_before_the_same_time_rule(service, caps):
    """Same reasoning as the daily cap: no other time would help either."""
    object.__setattr__(settings, "MAX_ACTIVE_RESERVATIONS", 3)
    with pytest.raises(MaxReservationsError):
        await _attempt(service, _slot(), already_at_that_time=True, active=3)


@pytest.mark.asyncio
async def test_room_on_the_day_still_does_not_buy_the_same_instant_twice(service, caps):
    """The rule is not a weaker restatement of the daily cap — with four of five
    slots left on the day, this instant is still spent."""
    with pytest.raises(DuplicateSlotTimeError):
        await _attempt(service, _slot(), already_at_that_time=True, on_day=1)


# ── what the user is told ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_message_names_the_local_time(service, caps):
    """The bot renders `e.message` verbatim, and the time has to be the user's
    own 04:00 PM — not the UTC instant the row is stored as."""
    with pytest.raises(DuplicateSlotTimeError) as exc:
        await _attempt(service, _slot(), already_at_that_time=True)

    assert exc.value.local_time == "04:00 PM"
    assert "04:00 PM" in exc.value.message


def test_the_message_stands_alone_without_a_time():
    """The argument is optional, so the fallback still has to be a sentence."""
    message = DuplicateSlotTimeError().message
    assert "at this time" in message
    assert "None" not in message
