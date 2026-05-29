import random
import string
import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.user import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(User, session)

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        stmt = (
            select(User)
            .where(User.telegram_id == telegram_id)
            .options(selectinload(User.country_rel))
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_by_public_code(self, code: str) -> User | None:
        return await self.first_by(public_user_code=code)

    async def exists_by_telegram_id(self, telegram_id: int) -> bool:
        stmt = select(User.id).where(User.telegram_id == telegram_id).limit(1)
        result = await self.session.execute(stmt)
        return result.scalar() is not None

    async def generate_unique_code(self) -> str:
        while True:
            code = "".join(random.choices(string.digits, k=6))
            if not await self.first_by(public_user_code=code):
                return code

    async def apply_score_delta(self, user_id: uuid.UUID, delta: int) -> None:
        """Atomically increment or decrement participation_score without a read-modify-write."""
        stmt = (
            update(User)
            .where(User.id == user_id)
            .values(participation_score=User.participation_score + delta)
            .execution_options(synchronize_session=False)
        )
        await self.session.execute(stmt)

    async def create(
        self,
        *,
        telegram_id: int,
        full_name: str,
        username: str | None = None,
        gender: str | None = None,
        country_id: str | None = None,
    ) -> User:
        code = await self.generate_unique_code()
        user = User(
            telegram_id=telegram_id,
            public_user_code=code,
            full_name=full_name,
            username=username,
            gender=gender,
            country_id=country_id,
        )
        return await self.save(user)
