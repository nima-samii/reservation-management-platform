from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User

from app.db.session import AsyncSessionFactory
from app.services.user import UserService

logger = structlog.get_logger(__name__)


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
