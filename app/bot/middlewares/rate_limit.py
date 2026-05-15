from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User

from app.cache.client import redis_client
from app.cache.keys import CacheKey
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class RateLimitMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        from_user: User | None = data.get("event_from_user")
        if from_user is None:
            return await handler(event, data)

        telegram_id = from_user.id

        key = CacheKey.rate_limit(telegram_id)
        allowed, retry_after = await redis_client.check_rate_limit(
            key=key,
            max_requests=settings.RATE_LIMIT_REQUESTS,
            window_seconds=settings.RATE_LIMIT_WINDOW_SECONDS,
        )

        if not allowed:
            logger.warning("rate_limited", telegram_id=telegram_id)
            from aiogram.types import Update
            update: Update | None = data.get("event_update")
            if update and update.message:
                await update.message.answer(
                    f"⚠️ Too many requests. Please wait {retry_after}s."
                )
            elif update and update.callback_query:
                await update.callback_query.answer(
                    f"⚠️ Too many requests. Please wait {retry_after}s.",
                    show_alert=True,
                )
            return None

        return await handler(event, data)
