"""The configurable per-day cap — mocked repos, no DB.

What the daily *window* is, and whether it can be raced, are settled elsewhere:
tests/test_repositories/test_daily_reservation_count.py pins the local-day
boundary against real PostgreSQL, and
tests/test_services/test_daily_limit_concurrency.py pins the locking. What is
left for this module is the arithmetic and the wiring — that the service reads
MAX_DAILY_RESERVATIONS live, compares it the right way round, and reports the
configured number back to the user.
"""
import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import pytz

from app.core.config import settings
from app.core.exceptions import DailyLimitError
from app.services.reservation import ReservationService

FIXED_NOW = datetime(2026, 7, 9, 10, 0, tzinfo=timezone.utc)
TZ = pytz.timezone(settings.TIMEZONE)


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
def daily_limit():
    """Set the cap the way the admin panel does — on the live singleton.

    `settings` is process-wide and mutable, and PATCH /admin/settings mutates it
    in place rather than rebuilding it, so this is the real mechanism and not a
    test shortcut. Restored afterwards so one test cannot leak into the next.
    """
    original = settings.MAX_DAILY_RESERVATIONS

    def _set(value: int) -> None:
        object.__setattr__(settings, "MAX_DAILY_RESERVATIONS", value)

    yield _set
    object.__setattr__(settings, "MAX_DAILY_RESERVATIONS", original)


def _slot():
    return SimpleNamespace(
        id=uuid.uuid4(),
        slot_datetime=FIXED_NOW + timedelta(days=2),
        is_booked=False,
        channel_id=uuid.uuid4(),
    )


async def _attempt(service, *, already_booked: int):
    """Run one booking against a day that already holds `already_booked`."""
    slot = _slot()
    reservation = SimpleNamespace(id=uuid.uuid4())

    service._slot_repo.get_slot_with_lock = AsyncMock(return_value=slot)
    service._res_repo.count_reservations_on_date = AsyncMock(return_value=already_booked)
    service._res_repo.count_active_reservations = AsyncMock(return_value=0)
    # The same-time rule is a separate axis with its own module; keep it out of
    # the way so a cap failure here can only mean the cap.
    service._res_repo.has_reservation_at_time = AsyncMock(return_value=False)
    service._res_repo.create = AsyncMock(return_value=reservation)
    service._res_repo.get_reservation_with_details = AsyncMock(return_value=reservation)
    service._score_svc.award_reservation_reward = AsyncMock(
        return_value=SimpleNamespace(id=uuid.uuid4(), transaction_type="reservation_reward")
    )

    with patch("app.services.reservation.enqueue_score_notification"):
        return await service._perform_booking(uuid.uuid4(), slot.id)


# ── the cap itself ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "limit,already_booked",
    [
        (1, 0),
        (2, 0), (2, 1),
        (3, 0), (3, 1), (3, 2),
        (5, 4),
    ],
)
async def test_booking_is_allowed_below_the_cap(service, daily_limit, limit, already_booked):
    daily_limit(limit)
    assert await _attempt(service, already_booked=already_booked) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "limit,already_booked",
    [
        (1, 1),
        (2, 2),
        (3, 3),
        (5, 5),
        # Above the cap, not merely at it: a limit lowered after the bookings
        # were made must still refuse the next one rather than fall through an
        # equality check.
        (1, 3),
        (2, 7),
    ],
)
async def test_booking_is_refused_at_or_above_the_cap(
    service, daily_limit, limit, already_booked
):
    daily_limit(limit)
    with pytest.raises(DailyLimitError):
        await _attempt(service, already_booked=already_booked)


@pytest.mark.asyncio
async def test_the_cap_is_read_live_not_captured(service, daily_limit):
    """The admin panel mutates the settings singleton without a restart, so the
    same service instance must see a new cap on its very next booking."""
    daily_limit(1)
    with pytest.raises(DailyLimitError):
        await _attempt(service, already_booked=1)

    daily_limit(3)
    assert await _attempt(service, already_booked=1) is not None

    daily_limit(1)
    with pytest.raises(DailyLimitError):
        await _attempt(service, already_booked=1)


# ── what the user is told ─────────────────────────────────────────────────────


def test_the_default_cap_keeps_the_original_wording():
    """Unchanged copy at the default, so the shipped EN/AR strings still match."""
    assert DailyLimitError().message == "You already have a reservation for this day."


def test_a_raised_cap_is_named_in_the_message():
    assert "3" in DailyLimitError(3).message


@pytest.mark.asyncio
async def test_the_error_carries_the_configured_cap(service, daily_limit):
    """The handler renders `e.message`, so the number the user sees comes from
    here — it must be the configured one, not a hard-coded 1."""
    daily_limit(4)
    with pytest.raises(DailyLimitError) as exc:
        await _attempt(service, already_booked=4)

    assert exc.value.max_per_day == 4
    assert "4" in exc.value.message


# ── the day the cap is counted over ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_cap_is_counted_over_the_slot_s_local_date(service, daily_limit):
    """Guards the seam between the counting query and the rule using it.

    The repository counts a *local calendar date*; passing a datetime (or a
    UTC-derived date) would silently reintroduce the UTC-day window that phase
    one removed.
    """
    daily_limit(2)
    slot = _slot()

    service._slot_repo.get_slot_with_lock = AsyncMock(return_value=slot)
    service._res_repo.count_reservations_on_date = AsyncMock(return_value=0)
    service._res_repo.count_active_reservations = AsyncMock(return_value=0)
    service._res_repo.has_reservation_at_time = AsyncMock(return_value=False)
    service._res_repo.create = AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4()))
    service._res_repo.get_reservation_with_details = AsyncMock(return_value=SimpleNamespace())
    service._score_svc.award_reservation_reward = AsyncMock(
        return_value=SimpleNamespace(id=uuid.uuid4(), transaction_type="reservation_reward")
    )

    user_id = uuid.uuid4()
    with patch("app.services.reservation.enqueue_score_notification"):
        await service._perform_booking(user_id, slot.id)

    (passed_user, passed_day), _ = service._res_repo.count_reservations_on_date.await_args
    assert passed_user == user_id
    # A date, never a datetime — datetime subclasses date, so isinstance would
    # accept exactly the value this is here to reject.
    assert type(passed_day) is date
    assert passed_day == slot.slot_datetime.astimezone(TZ).date()
