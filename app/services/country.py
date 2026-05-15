from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.country import Country
from app.repositories.country import CountryRepository


class CountryService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = CountryRepository(session)

    async def search(self, query: str) -> list[Country]:
        if not query.strip():
            return await self._repo.get_all_active()
        return await self._repo.search(query.strip())

    async def get_all(self) -> list[Country]:
        return await self._repo.get_all_active()

    async def get_by_code(self, code: str) -> Country | None:
        return await self._repo.get_by_code(code)
