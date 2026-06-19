"""Tests for the reservation-cancellation notification path — mocked, no DB.

Covers:
  * a delivery failure never raises (so it can never roll back the cancellation)
  * bot-blocked users are skipped
  * the message includes the reason when provided
  * the scheduler job wrapper swallows any error from delivery
"""
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.reservation_notification import ReservationNotificationService


def _make_reservation(bot_blocked=False, telegram_id=12345):
    return SimpleNamespace(
        id=uuid.uuid4(),
        user=SimpleNamespace(
            id=uuid.uuid4(), telegram_id=telegram_id, bot_blocked=bot_blocked
        ),
        slot=SimpleNamespace(
            slot_datetime=datetime(2026, 6, 20, 15, 0, tzinfo=timezone.utc),
        ),
        channel=SimpleNamespace(name="Channel 1"),
    )


@pytest.fixture
def svc():
    s = ReservationNotificationService.__new__(ReservationNotificationService)
    s._session = AsyncMock()
    s._res_repo = AsyncMock()
    s._notif = AsyncMock()
    s._notif.send = AsyncMock(return_value=(True, None))
    return s


@pytest.mark.asyncio
async def test_sends_cancellation_with_reason(svc):
    res = _make_reservation()
    svc._res_repo.get_reservation_with_details = AsyncMock(return_value=res)

    await svc.deliver_cancellation(res.id, reason="Slot double-booked")

    svc._notif.send.assert_awaited_once()
    telegram_id, text = svc._notif.send.await_args.args
    assert telegram_id == res.user.telegram_id
    assert "cancelled by the support team" in text
    assert "Reason: Slot double-booked" in text
    # Cancelled reservation's details are included.
    assert "Channel 1" in text
    assert "20 June 2026" in text


@pytest.mark.asyncio
async def test_omits_reason_line_when_absent(svc):
    res = _make_reservation()
    svc._res_repo.get_reservation_with_details = AsyncMock(return_value=res)

    await svc.deliver_cancellation(res.id, reason=None)

    _telegram_id, text = svc._notif.send.await_args.args
    assert "Reason:" not in text


@pytest.mark.asyncio
async def test_bot_blocked_user_is_skipped(svc):
    res = _make_reservation(bot_blocked=True)
    svc._res_repo.get_reservation_with_details = AsyncMock(return_value=res)

    await svc.deliver_cancellation(res.id)

    svc._notif.send.assert_not_called()


@pytest.mark.asyncio
async def test_delivery_failure_does_not_raise(svc):
    res = _make_reservation()
    svc._res_repo.get_reservation_with_details = AsyncMock(return_value=res)
    svc._notif.send = AsyncMock(return_value=(False, "Telegram: chat not found"))

    # Must NOT raise — the cancellation has already committed.
    await svc.deliver_cancellation(res.id, reason="x")


@pytest.mark.asyncio
async def test_missing_reservation_is_noop(svc):
    svc._res_repo.get_reservation_with_details = AsyncMock(return_value=None)

    await svc.deliver_cancellation(uuid.uuid4())

    svc._notif.send.assert_not_called()


@pytest.mark.asyncio
async def test_job_wrapper_swallows_delivery_error():
    """run_..._job must never propagate — a failed send can't break anything."""
    from app.schedulers.jobs import reservation_notification as job_mod

    failing_svc = MagicMock()
    failing_svc.deliver_cancellation = AsyncMock(side_effect=RuntimeError("telegram down"))

    # AsyncSessionFactory() used as `async with` context manager.
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=AsyncMock())
    cm.__aexit__ = AsyncMock(return_value=False)

    with patch.object(job_mod, "AsyncSessionFactory", return_value=cm), patch.object(
        job_mod, "ReservationNotificationService", return_value=failing_svc
    ), patch("app.bot.client.get_bot", return_value=MagicMock()):
        # Should complete without raising.
        await job_mod.run_reservation_cancellation_notification_job(
            str(uuid.uuid4()), "reason"
        )
