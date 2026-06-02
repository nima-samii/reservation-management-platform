import uuid
from datetime import date, datetime, timedelta
from typing import Optional

import pytz
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin.deps import get_current_admin
from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import get_db_session
from app.repositories.admin_audit_log import AdminAuditLogRepository
from app.repositories.broadcast import ScheduleEventRepository

router = APIRouter(tags=["admin-schedule-events"])
logger = get_logger(__name__)
TZ = pytz.timezone(settings.TIMEZONE)


def _today_local() -> date:
    return datetime.now(TZ).date()


def _event_to_dict(ev) -> dict:
    return {
        "id": str(ev.id),
        "channel_id": str(ev.channel_id) if ev.channel_id else None,
        "channel_name": ev.channel.name if ev.channel else None,
        "event_date": ev.event_date.isoformat(),
        "title": ev.title,
        "sort_order": ev.sort_order,
        "is_active": ev.is_active,
    }


class CreateEventBody(BaseModel):
    channel_id: Optional[uuid.UUID] = None
    event_date: date
    title: str
    sort_order: int = 0
    is_active: bool = True


class PatchEventBody(BaseModel):
    title: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


@router.get("")
async def list_events(
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    channel_id: Optional[uuid.UUID] = Query(None),
    session: AsyncSession = Depends(get_db_session),
    _admin: str = Depends(get_current_admin),
) -> list[dict]:
    today = _today_local()
    effective_from = date_from or today
    effective_to = date_to or (today + timedelta(days=30))

    repo = ScheduleEventRepository(session)
    events = await repo.get_events_in_range(effective_from, effective_to, channel_id)
    return [_event_to_dict(ev) for ev in events]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_event(
    body: CreateEventBody,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    admin: str = Depends(get_current_admin),
) -> dict:
    from app.db.models.schedule_event import ScheduleEvent

    ev = ScheduleEvent(
        channel_id=body.channel_id,
        event_date=body.event_date,
        title=body.title,
        sort_order=body.sort_order,
        is_active=body.is_active,
    )
    repo = ScheduleEventRepository(session)
    ev = await repo.save(ev)
    if ev.channel_id:
        await session.refresh(ev, ["channel"])

    audit_repo = AdminAuditLogRepository(session)
    ip = request.client.host if request.client else None
    await audit_repo.log(
        action="schedule_event_created",
        admin_username=admin,
        entity_type="schedule_event",
        entity_id=str(ev.id),
        details=f"date={body.event_date} title={body.title!r}",
        ip_address=ip,
    )
    logger.info("admin_schedule_event_created", event_id=str(ev.id), admin=admin)
    return _event_to_dict(ev)


@router.patch("/{event_id}")
async def patch_event(
    event_id: uuid.UUID,
    body: PatchEventBody,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    admin: str = Depends(get_current_admin),
) -> dict:
    repo = ScheduleEventRepository(session)
    ev = await repo.get_by_id(event_id)
    if not ev:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")

    if body.title is not None:
        ev.title = body.title
    if body.sort_order is not None:
        ev.sort_order = body.sort_order
    if body.is_active is not None:
        ev.is_active = body.is_active

    ev = await repo.save(ev)
    if ev.channel_id:
        await session.refresh(ev, ["channel"])

    audit_repo = AdminAuditLogRepository(session)
    ip = request.client.host if request.client else None
    await audit_repo.log(
        action="schedule_event_patched",
        admin_username=admin,
        entity_type="schedule_event",
        entity_id=str(event_id),
        details=str(body.model_dump(exclude_none=True)),
        ip_address=ip,
    )
    return _event_to_dict(ev)


@router.delete("/{event_id}", status_code=status.HTTP_200_OK)
async def delete_event(
    event_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    admin: str = Depends(get_current_admin),
) -> dict:
    repo = ScheduleEventRepository(session)
    ev = await repo.get_by_id(event_id)
    if not ev:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")

    ev.is_active = False
    await repo.save(ev)

    audit_repo = AdminAuditLogRepository(session)
    ip = request.client.host if request.client else None
    await audit_repo.log(
        action="schedule_event_deleted",
        admin_username=admin,
        entity_type="schedule_event",
        entity_id=str(event_id),
        details="soft delete: is_active=false",
        ip_address=ip,
    )
    return {"id": str(event_id), "deleted": True}
