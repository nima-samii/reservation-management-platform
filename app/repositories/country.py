from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.country import Country
from app.repositories.base import BaseRepository


class CountryRepository(BaseRepository[Country]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Country, session)

    async def search(self, query: str, limit: int = 20) -> list[Country]:
        stmt = (
            select(Country)
            .where(
                Country.is_active == True,  # noqa: E712
                func.lower(Country.name).contains(query.lower()),
            )
            .order_by(Country.name.asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_all_active(self) -> list[Country]:
        stmt = (
            select(Country)
            .where(Country.is_active == True)  # noqa: E712
            .order_by(Country.name.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_code(self, code: str) -> Country | None:
        return await self.first_by(code=code.upper())
