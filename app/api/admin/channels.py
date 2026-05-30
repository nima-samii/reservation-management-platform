from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin.deps import get_current_admin
from app.api.admin.schemas.reservations import ChannelListItem
from app.db.session import get_db_session
from app.repositories.channel import ChannelRepository

router = APIRouter(tags=["admin-channels"])


@router.get("", response_model=list[ChannelListItem])
async def list_channels(
    session: AsyncSession = Depends(get_db_session),
    _admin: str = Depends(get_current_admin),
) -> list[ChannelListItem]:
    repo = ChannelRepository(session)
    channels = await repo.get_all_channels()
    return [ChannelListItem.model_validate(ch) for ch in channels]
