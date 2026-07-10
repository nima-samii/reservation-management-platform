import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin.deps import get_current_admin
from app.api.admin.schemas.channels import (
    ChannelOut,
    CreateChannelBody,
    MoveChannelBody,
    UpdateChannelBody,
)
from app.db.models.channel import Channel
from app.db.session import get_db_session
from app.repositories.admin_audit_log import AdminAuditLogRepository
from app.repositories.channel import ChannelRepository

router = APIRouter(tags=["admin-channels"])


async def _get_or_404(repo: ChannelRepository, channel_id: uuid.UUID) -> Channel:
    channel = await repo.get_by_id(channel_id)
    if not channel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")
    return channel


@router.get("", response_model=list[ChannelOut])
async def list_channels(
    session: AsyncSession = Depends(get_db_session),
    _admin: str = Depends(get_current_admin),
) -> list[Channel]:
    repo = ChannelRepository(session)
    return await repo.get_all_channels()


@router.get("/{channel_id}", response_model=ChannelOut)
async def get_channel(
    channel_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    _admin: str = Depends(get_current_admin),
) -> Channel:
    repo = ChannelRepository(session)
    return await _get_or_404(repo, channel_id)


@router.post("", response_model=ChannelOut, status_code=status.HTTP_201_CREATED)
async def create_channel(
    body: CreateChannelBody,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    admin: str = Depends(get_current_admin),
) -> Channel:
    repo = ChannelRepository(session)
    next_priority = await repo.get_max_priority() + 1

    channel = Channel(
        name=body.name,
        telegram_channel_id=body.telegram_channel_id,
        invite_link=body.invite_link,
        priority=next_priority,
        is_active=True,
    )
    try:
        channel = await repo.save(channel)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A channel with this Telegram ID already exists",
        )

    audit_repo = AdminAuditLogRepository(session)
    ip = request.client.host if request.client else None
    await audit_repo.log(
        action="channel_created",
        admin_username=admin,
        entity_type="channel",
        entity_id=str(channel.id),
        details=f"name={body.name!r} telegram_channel_id={body.telegram_channel_id}",
        ip_address=ip,
    )
    return channel


@router.patch("/{channel_id}", response_model=ChannelOut)
async def update_channel(
    channel_id: uuid.UUID,
    body: UpdateChannelBody,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    admin: str = Depends(get_current_admin),
) -> Channel:
    repo = ChannelRepository(session)
    channel = await _get_or_404(repo, channel_id)

    if body.name is not None:
        channel.name = body.name
    if body.invite_link is not None:
        channel.invite_link = body.invite_link
    if body.is_active is not None:
        channel.is_active = body.is_active

    channel = await repo.save(channel)

    audit_repo = AdminAuditLogRepository(session)
    ip = request.client.host if request.client else None
    await audit_repo.log(
        action="channel_updated",
        admin_username=admin,
        entity_type="channel",
        entity_id=str(channel_id),
        details=str(body.model_dump(exclude_none=True)),
        ip_address=ip,
    )
    return channel


@router.delete("/{channel_id}")
async def delete_channel(
    channel_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    admin: str = Depends(get_current_admin),
) -> dict:
    repo = ChannelRepository(session)
    channel = await _get_or_404(repo, channel_id)

    if await repo.has_any_slots_or_reservations(channel_id):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Cannot delete: this channel has existing reservation slots or "
                "reservations. Disable it instead."
            ),
        )

    try:
        await repo.delete(channel)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Cannot delete: this channel has existing reservation slots or "
                "reservations. Disable it instead."
            ),
        )

    audit_repo = AdminAuditLogRepository(session)
    ip = request.client.host if request.client else None
    await audit_repo.log(
        action="channel_deleted",
        admin_username=admin,
        entity_type="channel",
        entity_id=str(channel_id),
        details=f"name={channel.name!r}",
        ip_address=ip,
    )
    return {"id": str(channel_id), "deleted": True}


@router.post("/{channel_id}/reorder", response_model=ChannelOut)
async def reorder_channel(
    channel_id: uuid.UUID,
    body: MoveChannelBody,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    admin: str = Depends(get_current_admin),
) -> Channel:
    repo = ChannelRepository(session)
    channel = await _get_or_404(repo, channel_id)

    neighbor = await repo.get_neighbor(channel, body.direction)
    if neighbor is None:
        # Already at the top/bottom — no-op, not an error.
        return channel

    channel.priority, neighbor.priority = neighbor.priority, channel.priority
    await repo.save(neighbor)
    channel = await repo.save(channel)

    audit_repo = AdminAuditLogRepository(session)
    ip = request.client.host if request.client else None
    await audit_repo.log(
        action="channel_reordered",
        admin_username=admin,
        entity_type="channel",
        entity_id=str(channel_id),
        details=f"direction={body.direction} swapped_with={neighbor.id}",
        ip_address=ip,
    )
    return channel
