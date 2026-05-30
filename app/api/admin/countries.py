import uuid
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin.deps import get_current_admin
from app.db.session import get_db_session
from app.repositories.country import CountryRepository


class CountryOut(BaseModel):
    id: uuid.UUID
    name: str
    code: str
    flag_emoji: Optional[str] = None

    model_config = {"from_attributes": True}


router = APIRouter(tags=["admin-countries"])


@router.get("/countries", response_model=list[CountryOut])
async def list_countries(
    session: AsyncSession = Depends(get_db_session),
    _admin: str = Depends(get_current_admin),
) -> list[CountryOut]:
    repo = CountryRepository(session)
    countries = await repo.get_all_active()
    return [CountryOut.model_validate(c) for c in countries]
