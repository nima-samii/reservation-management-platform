from typing import Any

from aiogram.filters import BaseFilter
from aiogram.types import Message

from app.db.models.user import User


class IsRegisteredFilter(BaseFilter):
    """Passes if db_user is present (injected by UserContextMiddleware)."""

    async def __call__(self, message: Message, db_user: User | None = None, **kwargs: Any) -> bool:
        return db_user is not None


class IsNotRegisteredFilter(BaseFilter):
    async def __call__(self, message: Message, db_user: User | None = None, **kwargs: Any) -> bool:
        return db_user is None
