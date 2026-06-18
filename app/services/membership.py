import hashlib

from aiogram import Bot
from aiogram.enums import ChatMemberStatus

from app.cache.client import redis_client
from app.cache.keys import CacheKey
from app.core.config import ChannelConfig, settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Statuses that count as "currently a member" of a channel.
_VALID_STATUSES = {
    ChatMemberStatus.MEMBER,
    ChatMemberStatus.ADMINISTRATOR,
    ChatMemberStatus.CREATOR,
}


def _channels_signature(channels: list[ChannelConfig]) -> str:
    """Stable short hash of the configured channel IDs (order-independent).

    Used in the cache key so that adding/removing a required channel
    invalidates all previously cached membership results.
    """
    raw = ",".join(str(cid) for cid in sorted(c.id for c in channels))
    return hashlib.md5(raw.encode()).hexdigest()[:8]


class MembershipService:
    """Verifies a user is a member of every mandatory channel.

    Successful checks are cached in Redis for `MEMBERSHIP_CACHE_TTL` seconds so
    repeated updates from a verified user skip the Telegram API entirely.
    """

    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def check_user_membership(self, user_id: int) -> bool:
        channels = settings.required_channels

        # Feature disabled — no channels configured.
        if not channels:
            return True

        cache_key = CacheKey.membership(user_id, _channels_signature(channels))
        if await redis_client.exists(cache_key):
            return True

        for channel in channels:
            if not await self._is_member(channel.id, user_id):
                return False

        # Member of all channels — cache the success only.
        await redis_client.set(cache_key, "1", ttl=settings.MEMBERSHIP_CACHE_TTL)
        return True

    async def _is_member(self, channel_id: int, user_id: int) -> bool:
        try:
            member = await self._bot.get_chat_member(
                chat_id=channel_id, user_id=user_id
            )
        except Exception as exc:  # noqa: BLE001 — verification must never crash the bot
            logger.warning(
                "membership_check_failed",
                channel_id=channel_id,
                user_id=user_id,
                error=str(exc),
            )
            return False
        return member.status in _VALID_STATUSES
