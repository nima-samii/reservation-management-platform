from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware, Bot
from aiogram.types import TelegramObject, User

from app.bot.keyboards.inline.membership import (
    CHECK_MEMBERSHIP_CALLBACK,
    MEMBERSHIP_REQUIRED_ALERT,
    MEMBERSHIP_REQUIRED_TEXT,
    build_membership_keyboard,
)
from app.core.config import settings
from app.core.logging import get_logger
from app.services.membership import MembershipService

logger = get_logger(__name__)


class MembershipMiddleware(BaseMiddleware):
    """Global guard enforcing mandatory channel membership.

    Registered on dp.update, so `event` is an Update. Runs before every handler
    so individual handlers never need to repeat the membership check.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # Feature disabled — behave exactly as before.
        if not settings.required_channels:
            return await handler(event, data)

        from_user: User | None = data.get("event_from_user")
        if from_user is None:
            return await handler(event, data)

        # `event` IS the Update here (outer middleware on dp.update). Read the
        # concrete event off it directly — data["event_update"] is NOT yet
        # populated at the outer-middleware stage, so relying on it silently
        # disables the prompt and the callback bypass below.
        message = getattr(event, "message", None) or getattr(event, "edited_message", None)
        callback = getattr(event, "callback_query", None)

        # Always let the "check membership" callback through — it re-verifies
        # and is the only way an unverified user can pass the gate.
        if callback and callback.data == CHECK_MEMBERSHIP_CALLBACK:
            return await handler(event, data)

        bot: Bot = data["bot"]
        service = MembershipService(bot)
        if await service.check_user_membership(from_user.id):
            return await handler(event, data)

        # Not a member of all channels — stop and prompt to join.
        logger.info("membership_gate_blocked", telegram_id=from_user.id)
        keyboard = build_membership_keyboard()

        # A normal OR edited message both carry a chat we can post the prompt into.
        if message:
            await message.answer(
                MEMBERSHIP_REQUIRED_TEXT,
                reply_markup=keyboard,
                parse_mode="Markdown",
            )
        elif callback:
            if callback.message:
                await callback.answer()
                await callback.message.answer(
                    MEMBERSHIP_REQUIRED_TEXT,
                    reply_markup=keyboard,
                    parse_mode="Markdown",
                )
            else:
                # Inline / too-old message: no chat to post into — surface an alert
                # so the user still sees why their action was blocked.
                await callback.answer(MEMBERSHIP_REQUIRED_ALERT, show_alert=True)
        return None
