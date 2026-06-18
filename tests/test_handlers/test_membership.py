"""Tests for the membership gate middleware and the check-membership callback."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.bot.handlers.membership import check_membership
from app.bot.keyboards.inline.membership import MEMBERSHIP_NOT_JOINED_ALERT
from app.bot.middlewares.membership import MembershipMiddleware
from app.core.config import settings
from app.services.membership import MembershipService


def _set_channels(monkeypatch, channels: list[tuple[int, str]]) -> None:
    for i in range(1, 6):
        monkeypatch.setattr(settings, f"REQUIRED_CHANNEL_{i}_ID", None, raising=False)
        monkeypatch.setattr(settings, f"REQUIRED_CHANNEL_{i}_URL", None, raising=False)
    for idx, (cid, url) in enumerate(channels, start=1):
        monkeypatch.setattr(settings, f"REQUIRED_CHANNEL_{idx}_ID", cid)
        monkeypatch.setattr(settings, f"REQUIRED_CHANNEL_{idx}_URL", url)


def _patch_check(monkeypatch, result):
    async def fake_check(self, user_id):
        return result

    monkeypatch.setattr(MembershipService, "check_user_membership", fake_check)


def _event(*, message=None, edited_message=None, callback=None):
    """Build the Update object passed as `event` to the outer middleware."""
    return SimpleNamespace(
        message=message, edited_message=edited_message, callback_query=callback
    )


def _data():
    # NOTE: no "event_update" key — it is intentionally absent, mirroring what
    # aiogram actually provides at the outer-middleware stage on dp.update.
    return {"event_from_user": SimpleNamespace(id=1), "bot": AsyncMock()}


# ── Middleware ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_middleware_passes_through_when_disabled(monkeypatch):
    _set_channels(monkeypatch, [])
    handler = AsyncMock(return_value="OK")

    result = await MembershipMiddleware()(handler, _event(message=AsyncMock()), _data())

    assert result == "OK"
    handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_middleware_allows_verified_member(monkeypatch):
    _set_channels(monkeypatch, [(-100, "https://t.me/x")])
    _patch_check(monkeypatch, True)
    handler = AsyncMock(return_value="OK")

    result = await MembershipMiddleware()(handler, _event(message=AsyncMock()), _data())

    assert result == "OK"
    handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_middleware_blocks_non_member_and_prompts(monkeypatch):
    _set_channels(monkeypatch, [(-100, "https://t.me/x")])
    _patch_check(monkeypatch, False)
    handler = AsyncMock()
    message = AsyncMock()

    result = await MembershipMiddleware()(handler, _event(message=message), _data())

    assert result is None
    handler.assert_not_awaited()
    message.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_middleware_prompts_on_edited_message(monkeypatch):
    _set_channels(monkeypatch, [(-100, "https://t.me/x")])
    _patch_check(monkeypatch, False)
    handler = AsyncMock()
    edited = AsyncMock()

    result = await MembershipMiddleware()(handler, _event(edited_message=edited), _data())

    assert result is None
    handler.assert_not_awaited()
    edited.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_middleware_blocks_callback_with_message_and_prompts(monkeypatch):
    _set_channels(monkeypatch, [(-100, "https://t.me/x")])
    _patch_check(monkeypatch, False)
    handler = AsyncMock()
    cb_message = AsyncMock()
    callback = AsyncMock()
    callback.data = "something_else"
    callback.message = cb_message

    result = await MembershipMiddleware()(handler, _event(callback=callback), _data())

    assert result is None
    handler.assert_not_awaited()
    callback.answer.assert_awaited_once_with()
    cb_message.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_middleware_blocks_callback_without_message_via_alert(monkeypatch):
    from app.bot.keyboards.inline.membership import MEMBERSHIP_REQUIRED_ALERT

    _set_channels(monkeypatch, [(-100, "https://t.me/x")])
    _patch_check(monkeypatch, False)
    handler = AsyncMock()
    callback = AsyncMock()
    callback.data = "something_else"
    callback.message = None  # inline / too-old message

    result = await MembershipMiddleware()(handler, _event(callback=callback), _data())

    assert result is None
    handler.assert_not_awaited()
    callback.answer.assert_awaited_once_with(MEMBERSHIP_REQUIRED_ALERT, show_alert=True)


@pytest.mark.asyncio
async def test_middleware_lets_check_membership_callback_bypass_gate(monkeypatch):
    _set_channels(monkeypatch, [(-100, "https://t.me/x")])

    async def must_not_run(self, user_id):  # pragma: no cover - asserts it isn't called
        raise AssertionError("membership should not be checked for the callback")

    monkeypatch.setattr(MembershipService, "check_user_membership", must_not_run)
    handler = AsyncMock(return_value="OK")
    callback = SimpleNamespace(data="check_membership", message=None)

    result = await MembershipMiddleware()(handler, _event(callback=callback), _data())

    assert result == "OK"
    handler.assert_awaited_once()


# ── Callback ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_callback_success_flow(monkeypatch):
    _patch_check(monkeypatch, True)
    callback = AsyncMock()
    callback.from_user = SimpleNamespace(id=1)
    callback.message = AsyncMock()

    await check_membership(callback, AsyncMock())

    callback.answer.assert_awaited_once_with()
    callback.message.edit_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_callback_failure_flow(monkeypatch):
    _patch_check(monkeypatch, False)
    callback = AsyncMock()
    callback.from_user = SimpleNamespace(id=1)
    callback.message = AsyncMock()

    await check_membership(callback, AsyncMock())

    callback.answer.assert_awaited_once_with(MEMBERSHIP_NOT_JOINED_ALERT, show_alert=True)
    callback.message.edit_text.assert_not_called()
