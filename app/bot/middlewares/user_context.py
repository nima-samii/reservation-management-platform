from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User

from app.db.session import AsyncSessionFactory
from app.services.user import UserService

logger = structlog.get_logger(__name__)

_BAN_MESSAGE = (
    "⛔ *Your account has been suspended.*\n\n"
    "You are no longer able to use this bot.\n"
    "If you believe this is an error, please contact our support team."
)


class UserContextMiddleware(BaseMiddleware):
    """
    Injects `db_user` into handler data so handlers don't need to
    call the DB themselves. Also syncs username passively.

    Registered on dp.update, so `event` is an Update object.
    Aiogram always populates data["event_from_user"] for us.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        from_user: User | None = data.get("event_from_user")

        if from_user:
            async with AsyncSessionFactory() as session:
                svc = UserService(session)
                user = await svc.get_or_none(from_user.id)
                if user:
                    if user.is_banned:
                        msg = getattr(event, "message", None) or getattr(event, "edited_message", None)
                        cbq = getattr(event, "callback_query", None)
                        if msg:
                            await msg.answer(_BAN_MESSAGE, parse_mode="Markdown")
                        elif cbq:
                            await cbq.answer(
                                "⛔ Your account has been suspended. Contact support.",
                                show_alert=True,
                            )
                        logger.info("banned_user_blocked", telegram_id=from_user.id)
                        return

                    full_name = " ".join(
                        filter(None, [from_user.first_name, from_user.last_name])
                    )
                    await svc.sync_telegram_info(
                        from_user.id, from_user.username, full_name
                    )
                    await session.commit()

                data["db_user"] = user

            structlog.contextvars.bind_contextvars(
                telegram_id=from_user.id,
                username=from_user.username,
            )
        else:
            data["db_user"] = None

        return await handler(event, data)
