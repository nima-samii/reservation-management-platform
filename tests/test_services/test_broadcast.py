"""Tests for BroadcastService — mocked bot and repositories."""
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from app.services.broadcast import BroadcastService


def _make_channel(name="Echoes", tg_id=-100123, invite="https://t.me/+x"):
    return SimpleNamespace(
        id="chan-uuid",
        name=name,
        telegram_channel_id=tg_id,
        invite_link=invite,
        priority=0,
        is_active=True,
    )


def _make_sent_msg(message_id=42):
    return SimpleNamespace(message_id=message_id)


@pytest.fixture
def bot():
    b = AsyncMock()
    b.send_message = AsyncMock(return_value=_make_sent_msg(42))
    b.pin_chat_message = AsyncMock()
    b.unpin_chat_message = AsyncMock()
    b.delete_message = AsyncMock()
    return b


@pytest.fixture
def session():
    return AsyncMock()


@pytest.fixture
def service(session, bot):
    svc = BroadcastService.__new__(BroadcastService)
    svc._session = session
    svc._bot = bot
    svc._channel_repo = AsyncMock()
    svc._res_repo = AsyncMock()
    svc._broadcast_repo = AsyncMock()
    svc._event_repo = AsyncMock()
    svc._formatter = MagicMock()
    svc._formatter.render = MagicMock(return_value="<b>schedule text</b>")
    return svc


TODAY = date(2026, 5, 29)


# ── Deduplication ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_skips_already_sent_channel(service, bot):
    channel = _make_channel()
    existing = SimpleNamespace(status="sent")
    service._broadcast_repo.get_for_channel_and_date = AsyncMock(return_value=existing)

    result = await service._broadcast_channel(channel, TODAY)

    assert result == "skipped"
    bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_sends_when_no_previous_broadcast(service, bot):
    channel = _make_channel()
    service._broadcast_repo.get_for_channel_and_date = AsyncMock(return_value=None)
    service._broadcast_repo.get_previous_sent = AsyncMock(return_value=None)
    service._broadcast_repo.log_success = AsyncMock()
    service._res_repo.get_active_reservations_for_date_and_channel = AsyncMock(return_value=[])
    service._event_repo.get_for_date_and_channel = AsyncMock(return_value=[])

    result = await service._broadcast_channel(channel, TODAY)

    assert result == "sent"
    bot.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_sends_when_previous_failed(service, bot):
    channel = _make_channel()
    existing = SimpleNamespace(status="failed")
    service._broadcast_repo.get_for_channel_and_date = AsyncMock(return_value=existing)
    service._broadcast_repo.get_previous_sent = AsyncMock(return_value=None)
    service._broadcast_repo.log_success = AsyncMock()
    service._res_repo.get_active_reservations_for_date_and_channel = AsyncMock(return_value=[])
    service._event_repo.get_for_date_and_channel = AsyncMock(return_value=[])

    result = await service._broadcast_channel(channel, TODAY)

    assert result == "sent"


# ── Failure Handling ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_logs_failure_on_telegram_error(service, bot):
    from aiogram.exceptions import TelegramAPIError

    channel = _make_channel()
    service._broadcast_repo.get_for_channel_and_date = AsyncMock(return_value=None)
    service._broadcast_repo.log_failure = AsyncMock()
    service._res_repo.get_active_reservations_for_date_and_channel = AsyncMock(return_value=[])
    service._event_repo.get_for_date_and_channel = AsyncMock(return_value=[])

    bot.send_message = AsyncMock(side_effect=TelegramAPIError(method=None, message="blocked"))

    result = await service._broadcast_channel(channel, TODAY)

    assert result == "failed"
    service._broadcast_repo.log_failure.assert_called_once()


# ── Per-channel Filtering ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_per_channel_reservations_queried_separately(service, bot):
    ch1 = _make_channel(name="Channel1", tg_id=-100001)
    ch2 = _make_channel(name="Channel2", tg_id=-100002)
    ch1.id = "uuid-ch1"
    ch2.id = "uuid-ch2"

    service._channel_repo.get_active_channels_ordered = AsyncMock(return_value=[ch1, ch2])
    service._broadcast_repo.get_for_channel_and_date = AsyncMock(return_value=None)
    service._broadcast_repo.get_previous_sent = AsyncMock(return_value=None)
    service._broadcast_repo.log_success = AsyncMock()
    service._res_repo.get_active_reservations_for_date_and_channel = AsyncMock(return_value=[])
    service._event_repo.get_for_date_and_channel = AsyncMock(return_value=[])

    with patch("app.services.broadcast.datetime") as mock_dt:
        mock_dt.now.return_value.date.return_value = TODAY
        await service.run_daily_broadcast()

    calls = service._res_repo.get_active_reservations_for_date_and_channel.call_args_list
    queried_channel_ids = [c.args[0] for c in calls]
    assert "uuid-ch1" in queried_channel_ids
    assert "uuid-ch2" in queried_channel_ids
    assert len(queried_channel_ids) == 2


# ── Pinning ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pins_new_message(service, bot):
    channel = _make_channel()
    service._broadcast_repo.get_for_channel_and_date = AsyncMock(return_value=None)
    service._broadcast_repo.get_previous_sent = AsyncMock(return_value=None)
    service._broadcast_repo.log_success = AsyncMock()
    service._res_repo.get_active_reservations_for_date_and_channel = AsyncMock(return_value=[])
    service._event_repo.get_for_date_and_channel = AsyncMock(return_value=[])

    await service._broadcast_channel(channel, TODAY)

    bot.pin_chat_message.assert_called_once_with(
        chat_id=channel.telegram_channel_id,
        message_id=42,
        disable_notification=True,
    )


@pytest.mark.asyncio
async def test_unpins_and_deletes_previous_message(service, bot):
    channel = _make_channel()
    previous = SimpleNamespace(status="sent", telegram_message_id=99)

    service._broadcast_repo.get_for_channel_and_date = AsyncMock(return_value=None)
    service._broadcast_repo.get_previous_sent = AsyncMock(return_value=previous)
    service._broadcast_repo.log_success = AsyncMock()
    service._res_repo.get_active_reservations_for_date_and_channel = AsyncMock(return_value=[])
    service._event_repo.get_for_date_and_channel = AsyncMock(return_value=[])

    await service._broadcast_channel(channel, TODAY)

    bot.unpin_chat_message.assert_called_once_with(
        chat_id=channel.telegram_channel_id,
        message_id=99,
    )
    bot.delete_message.assert_called_once_with(
        chat_id=channel.telegram_channel_id,
        message_id=99,
    )


@pytest.mark.asyncio
async def test_pin_failure_does_not_crash_broadcast(service, bot):
    from aiogram.exceptions import TelegramAPIError

    channel = _make_channel()
    service._broadcast_repo.get_for_channel_and_date = AsyncMock(return_value=None)
    service._broadcast_repo.get_previous_sent = AsyncMock(return_value=None)
    service._broadcast_repo.log_success = AsyncMock()
    service._res_repo.get_active_reservations_for_date_and_channel = AsyncMock(return_value=[])
    service._event_repo.get_for_date_and_channel = AsyncMock(return_value=[])
    bot.pin_chat_message = AsyncMock(side_effect=TelegramAPIError(method=None, message="no rights"))

    result = await service._broadcast_channel(channel, TODAY)

    assert result == "sent"
