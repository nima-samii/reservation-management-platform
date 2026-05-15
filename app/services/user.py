from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AlreadyExistsError, NotFoundError
from app.core.logging import get_logger
from app.db.models.user import User
from app.repositories.user import UserRepository

logger = get_logger(__name__)


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = UserRepository(session)

    async def get_or_none(self, telegram_id: int) -> User | None:
        return await self._repo.get_by_telegram_id(telegram_id)

    async def is_registered(self, telegram_id: int) -> bool:
        return await self._repo.exists_by_telegram_id(telegram_id)

    async def register(
        self,
        *,
        telegram_id: int,
        full_name: str,
        username: str | None = None,
        gender: str | None = None,
        country_id: str | None = None,
    ) -> User:
        existing = await self._repo.get_by_telegram_id(telegram_id)
        if existing:
            raise AlreadyExistsError("User")

        user = await self._repo.create(
            telegram_id=telegram_id,
            full_name=full_name,
            username=username,
            gender=gender,
            country_id=country_id,
        )
        logger.info("user_registered", telegram_id=telegram_id, code=user.public_user_code)
        return user

    async def update_profile(
        self,
        telegram_id: int,
        *,
        full_name: str | None = None,
        gender: str | None = None,
        country_id: str | None = None,
    ) -> User:
        user = await self._repo.get_by_telegram_id(telegram_id)
        if not user:
            raise NotFoundError("User")

        if full_name is not None:
            user.full_name = full_name
        if gender is not None:
            user.gender = gender
        if country_id is not None:
            user.country_id = country_id  # type: ignore[assignment]

        user = await self._repo.save(user)
        logger.info("user_profile_updated", telegram_id=telegram_id)
        return user

    async def sync_telegram_info(
        self, telegram_id: int, username: str | None, full_name: str
    ) -> None:
        user = await self._repo.get_by_telegram_id(telegram_id)
        if not user:
            return
        changed = False
        if user.username != username:
            user.username = username
            changed = True
        if changed:
            await self._repo.save(user)
