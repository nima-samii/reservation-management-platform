from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update, User

from app.cache.client import redis_client
from app.cache.keys import CacheKey
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class AntiFloodMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        from_user: User | None = data.get("event_from_user")
        if from_user is None:
            return await handler(event, data)

        key = CacheKey.anti_flood(from_user.id)
        allowed = await redis_client.check_anti_flood(
            key, settings.ANTI_FLOOD_SECONDS
        )

        if not allowed:
            # Answer callback queries silently to dismiss the loading spinner
            update: Update | None = data.get("event_update")
            if update and update.callback_query:
                await update.callback_query.answer("⚡ Slow down a bit!", show_alert=False)
            return None

        return await handler(event, data)
