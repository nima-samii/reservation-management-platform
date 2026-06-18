"""Tests for MembershipService — mocked bot and Redis."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.config import settings
from app.services.membership import MembershipService


def _set_channels(monkeypatch, channels: list[tuple[int, str]]) -> None:
    """Configure required channels by setting the underlying env fields."""
    for i in range(1, 6):
        monkeypatch.setattr(settings, f"REQUIRED_CHANNEL_{i}_ID", None, raising=False)
        monkeypatch.setattr(settings, f"REQUIRED_CHANNEL_{i}_URL", None, raising=False)
    for idx, (cid, url) in enumerate(channels, start=1):
        monkeypatch.setattr(settings, f"REQUIRED_CHANNEL_{idx}_ID", cid)
        monkeypatch.setattr(settings, f"REQUIRED_CHANNEL_{idx}_URL", url)


def _member(status: str) -> SimpleNamespace:
    return SimpleNamespace(status=status)


@pytest.fixture
def bot():
    return AsyncMock()


@pytest.fixture
def fake_redis(monkeypatch):
    r = AsyncMock()
    r.exists = AsyncMock(return_value=False)
    r.set = AsyncMock()
    monkeypatch.setattr("app.services.membership.redis_client", r)
    return r


@pytest.mark.asyncio
async def test_disabled_returns_true_without_api_or_cache(monkeypatch, bot, fake_redis):
    _set_channels(monkeypatch, [])

    result = await MembershipService(bot).check_user_membership(123)

    assert result is True
    bot.get_chat_member.assert_not_called()
    fake_redis.exists.assert_not_called()


@pytest.mark.asyncio
async def test_user_in_all_channels_returns_true_and_caches(monkeypatch, bot, fake_redis):
    _set_channels(monkeypatch, [(-100, "u1"), (-200, "u2")])
    bot.get_chat_member = AsyncMock(return_value=_member("member"))

    result = await MembershipService(bot).check_user_membership(123)

    assert result is True
    assert bot.get_chat_member.call_count == 2
    fake_redis.set.assert_called_once()


@pytest.mark.asyncio
async def test_accepts_admin_and_creator_statuses(monkeypatch, bot, fake_redis):
    _set_channels(monkeypatch, [(-100, "u1"), (-200, "u2")])
    bot.get_chat_member = AsyncMock(
        side_effect=[_member("administrator"), _member("creator")]
    )

    assert await MembershipService(bot).check_user_membership(123) is True


@pytest.mark.asyncio
async def test_user_missing_one_channel_returns_false(monkeypatch, bot, fake_redis):
    _set_channels(monkeypatch, [(-100, "u1"), (-200, "u2")])
    bot.get_chat_member = AsyncMock(side_effect=[_member("member"), _member("left")])

    result = await MembershipService(bot).check_user_membership(123)

    assert result is False
    fake_redis.set.assert_not_called()


@pytest.mark.asyncio
async def test_cache_hit_skips_api(monkeypatch, bot, fake_redis):
    _set_channels(monkeypatch, [(-100, "u1")])
    fake_redis.exists = AsyncMock(return_value=True)

    result = await MembershipService(bot).check_user_membership(123)

    assert result is True
    bot.get_chat_member.assert_not_called()
    fake_redis.set.assert_not_called()


@pytest.mark.asyncio
async def test_api_error_treated_as_not_member(monkeypatch, bot, fake_redis):
    _set_channels(monkeypatch, [(-100, "u1")])
    bot.get_chat_member = AsyncMock(side_effect=Exception("network down"))

    result = await MembershipService(bot).check_user_membership(123)

    assert result is False
    fake_redis.set.assert_not_called()


@pytest.mark.asyncio
async def test_cache_key_changes_when_channel_set_changes(monkeypatch, bot, fake_redis):
    """Adding/removing a required channel must invalidate the cached result."""
    _set_channels(monkeypatch, [(-100, "u1")])
    bot.get_chat_member = AsyncMock(return_value=_member("member"))

    await MembershipService(bot).check_user_membership(123)
    key_before = fake_redis.set.call_args.args[0]

    # Admin adds a second required channel.
    _set_channels(monkeypatch, [(-100, "u1"), (-200, "u2")])
    await MembershipService(bot).check_user_membership(123)
    key_after = fake_redis.set.call_args.args[0]

    assert key_before != key_after


@pytest.mark.asyncio
async def test_stale_cache_under_old_signature_is_not_reused(monkeypatch, bot, fake_redis):
    """A cache entry keyed to the OLD channel set must not satisfy the NEW set."""
    from app.cache.keys import CacheKey
    from app.services.membership import _channels_signature

    old_channels = [(-100, "u1")]
    new_channels = [(-100, "u1"), (-200, "u2")]
    _set_channels(monkeypatch, new_channels)

    # Only the old-signature key exists in the cache.
    old_sig = _channels_signature(
        [SimpleNamespace(id=cid) for cid, _ in old_channels]
    )
    old_key = CacheKey.membership(123, old_sig)
    fake_redis.exists = AsyncMock(side_effect=lambda k: k == old_key)
    # User is NOT in the newly added channel.
    bot.get_chat_member = AsyncMock(side_effect=[_member("member"), _member("left")])

    result = await MembershipService(bot).check_user_membership(123)

    assert result is False  # re-verified against the new set, ignored the stale key
    bot.get_chat_member.assert_awaited()
