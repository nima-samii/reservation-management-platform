import uuid
from datetime import datetime
from math import ceil
from typing import Optional

import pytz
from aiogram.exceptions import TelegramAPIError
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin.deps import get_current_admin
from app.api.admin.schemas.user_broadcast import (
    AudiencePreviewRequest,
    AudiencePreviewResponse,
    PaginatedUserBroadcasts,
    UserBroadcastCreate,
    UserBroadcastCreateResponse,
    UserBroadcastHistoryItem,
    UserBroadcastProgress,
)
from app.cache.client import redis_client
from app.cache.keys import CacheKey
from app.core.config import settings
from app.core.logging import get_logger
from app.db.models.user_broadcast import UserBroadcast
from app.db.session import get_db_session
from app.repositories.broadcast import BroadcastRepository
from app.repositories.channel import ChannelRepository
from app.repositories.admin_audit_log import AdminAuditLogRepository
from app.repositories.user_broadcast import UserBroadcastRepository
from app.schedulers.jobs.user_broadcast import run_user_broadcast_job
from app.services.audience import AudienceResolver
from app.services.broadcast import BroadcastService
from app.services.user_broadcast import UserBroadcastService

router = APIRouter(tags=["admin-broadcast"])
logger = get_logger(__name__)
TZ = pytz.timezone(settings.TIMEZONE)

_BROADCAST_RATE_LIMIT = 5
_BROADCAST_RATE_WINDOW = 600  # 10 minutes


# ── Schemas ───────────────────────────────────────────────────────────────────

class ManualBroadcastBody(BaseModel):
    channel_ids: list[uuid.UUID]
    message: str
    parse_mode: str = "HTML"

    @field_validator("channel_ids")
    @classmethod
    def non_empty(cls, v: list) -> list:
        if not v:
            raise ValueError("channel_ids must not be empty")
        return v

    @field_validator("message")
    @classmethod
    def validate_message(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 10:
            raise ValueError("message must be at least 10 characters")
        if len(v) > 4000:
            raise ValueError("message must not exceed 4000 characters")
        return v

    @field_validator("parse_mode")
    @classmethod
    def validate_parse_mode(cls, v: str) -> str:
        if v not in ("HTML", "Markdown", "plain"):
            raise ValueError("parse_mode must be HTML, Markdown, or plain")
        return v


class TriggerDailyBody(BaseModel):
    channel_ids: list[uuid.UUID] | None = None


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _check_rate_limit(admin: str) -> None:
    key = CacheKey.admin_broadcast_rate_limit(admin)
    allowed, retry_after = await redis_client.check_rate_limit(
        key, _BROADCAST_RATE_LIMIT, _BROADCAST_RATE_WINDOW
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. Try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/manual")
async def send_manual_broadcast(
    body: ManualBroadcastBody,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    admin: str = Depends(get_current_admin),
) -> list[dict]:
    await _check_rate_limit(admin)

    channel_repo = ChannelRepository(session)
    audit_repo = AdminAuditLogRepository(session)
    bot = request.app.state.bot

    results = []
    for cid in body.channel_ids:
        channel = await channel_repo.get_by_id(cid)
        if not channel:
            results.append(
                {"channel_id": str(cid), "channel_name": None, "success": False, "error": "Channel not found"}
            )
            continue
        if not channel.is_active:
            results.append(
                {"channel_id": str(cid), "channel_name": channel.name, "success": False, "error": "Channel is inactive"}
            )
            continue

        parse_mode = None if body.parse_mode == "plain" else body.parse_mode
        try:
            await bot.send_message(
                chat_id=channel.telegram_channel_id,
                text=body.message,
                parse_mode=parse_mode,
            )
            results.append(
                {"channel_id": str(cid), "channel_name": channel.name, "success": True, "error": None}
            )
            logger.info(
                "admin_manual_broadcast_sent",
                channel=channel.name,
                admin=admin,
            )
        except TelegramAPIError as exc:
            results.append(
                {"channel_id": str(cid), "channel_name": channel.name, "success": False, "error": str(exc)}
            )
            logger.error(
                "admin_manual_broadcast_failed",
                channel=channel.name,
                error=str(exc),
            )

    ip = request.client.host if request.client else None
    await audit_repo.log(
        action="manual_broadcast",
        admin_username=admin,
        entity_type="channel",
        entity_id=",".join(str(c) for c in body.channel_ids),
        details=f"parse_mode={body.parse_mode} chars={len(body.message)}",
        ip_address=ip,
    )
    return results


@router.post("/trigger-daily")
async def trigger_daily_broadcast(
    body: TriggerDailyBody,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    admin: str = Depends(get_current_admin),
) -> list[dict]:
    channel_repo = ChannelRepository(session)
    broadcast_repo = BroadcastRepository(session)
    audit_repo = AdminAuditLogRepository(session)
    bot = request.app.state.bot
    today = datetime.now(TZ).date()

    if body.channel_ids is None:
        channels = await channel_repo.get_active_channels_ordered()
        target_ids = [ch.id for ch in channels]
    else:
        target_ids = list(body.channel_ids)

    # Check for already-sent channels
    already_sent = []
    for cid in target_ids:
        log = await broadcast_repo.get_for_channel_and_date(cid, today)
        if log and log.status == "sent":
            ch = await channel_repo.get_by_id(cid)
            already_sent.append(
                {"channel_id": str(cid), "channel_name": ch.name if ch else None}
            )

    if already_sent:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Broadcast already sent today for these channels",
                "already_sent": already_sent,
            },
        )

    svc = BroadcastService(session, bot)
    results = await svc.broadcast_for_channel_ids(target_ids, today)

    ip = request.client.host if request.client else None
    await audit_repo.log(
        action="trigger_daily_broadcast",
        admin_username=admin,
        entity_type="broadcast",
        entity_id=",".join(str(c) for c in target_ids),
        details=f"channels={len(target_ids)}",
        ip_address=ip,
    )
    return results


@router.get("/logs")
async def get_broadcast_logs(
    broadcast_date: Optional[str] = Query(None, alias="date"),
    channel_id: Optional[uuid.UUID] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db_session),
    _admin: str = Depends(get_current_admin),
) -> dict:
    from datetime import date as date_type
    parsed_date: Optional[date_type] = None
    if broadcast_date:
        try:
            parsed_date = date_type.fromisoformat(broadcast_date)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="date must be YYYY-MM-DD",
            )
    else:
        parsed_date = datetime.now(TZ).date()

    repo = BroadcastRepository(session)
    items, total = await repo.admin_list(
        broadcast_date=parsed_date,
        channel_id=channel_id,
        page=page,
        page_size=page_size,
    )
    return {
        "items": items,
        "total": total,
        "page": page,
        "pages": max(1, ceil(total / page_size)),
    }


# ── User broadcasts ─────────────────────────────────────────────────────────


def _progress_percent(b: UserBroadcast) -> int:
    processed = b.success_count + b.failed_count + b.blocked_count
    if b.total_recipients <= 0:
        return 100 if b.status in ("completed", "failed") else 0
    return min(100, round(processed * 100 / b.total_recipients))


@router.post("/users/preview", response_model=AudiencePreviewResponse)
async def preview_user_audience(
    body: AudiencePreviewRequest,
    session: AsyncSession = Depends(get_db_session),
    _admin: str = Depends(get_current_admin),
) -> AudiencePreviewResponse:
    """Return the number of users a broadcast would reach. Uses the exact same
    resolver the sender uses, so the preview can never drift from delivery."""
    resolver = AudienceResolver(session)
    count = await resolver.count(body.audience_type)
    return AudiencePreviewResponse(count=count)


@router.post("/users", response_model=UserBroadcastCreateResponse, status_code=201)
async def create_user_broadcast(
    body: UserBroadcastCreate,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    admin: str = Depends(get_current_admin),
) -> UserBroadcastCreateResponse:
    await _check_rate_limit(admin)

    bot = request.app.state.bot
    svc = UserBroadcastService(session, bot)
    broadcast = await svc.create_broadcast(
        message=body.message,
        parse_mode=body.parse_mode,
        audience_type=body.audience_type,
        created_by=admin,
    )

    # Hand off delivery to the background scheduler — never block the request.
    scheduler = request.app.state.scheduler
    scheduler.add_job(
        run_user_broadcast_job,
        "date",
        args=[str(broadcast.id)],
        id=f"user_broadcast:{broadcast.id}",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    audit_repo = AdminAuditLogRepository(session)
    ip = request.client.host if request.client else None
    await audit_repo.log(
        action="user_broadcast_created",
        admin_username=admin,
        entity_type="user_broadcast",
        entity_id=str(broadcast.id),
        details=f"audience={body.audience_type} recipients={broadcast.total_recipients} parse_mode={body.parse_mode}",
        ip_address=ip,
    )

    return UserBroadcastCreateResponse(
        id=broadcast.id,
        status=broadcast.status,
        audience_type=broadcast.audience_type,
        total_recipients=broadcast.total_recipients,
    )


@router.get("/users", response_model=PaginatedUserBroadcasts)
async def list_user_broadcasts(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db_session),
    _admin: str = Depends(get_current_admin),
) -> PaginatedUserBroadcasts:
    repo = UserBroadcastRepository(session)
    rows, total = await repo.admin_list(page=page, page_size=page_size)
    return PaginatedUserBroadcasts(
        items=[
            UserBroadcastHistoryItem(
                id=b.id,
                audience_type=b.audience_type,
                status=b.status,
                message=b.message,
                total_recipients=b.total_recipients,
                success_count=b.success_count,
                failed_count=b.failed_count,
                blocked_count=b.blocked_count,
                created_at=b.created_at,
                completed_at=b.completed_at,
            )
            for b in rows
        ],
        total=total,
        page=page,
        pages=max(1, ceil(total / page_size)),
    )


@router.get("/users/{broadcast_id}", response_model=UserBroadcastProgress)
async def get_user_broadcast(
    broadcast_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    _admin: str = Depends(get_current_admin),
) -> UserBroadcastProgress:
    repo = UserBroadcastRepository(session)
    b = await repo.get_by_id(broadcast_id)
    if b is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Broadcast not found")
    return UserBroadcastProgress(
        id=b.id,
        status=b.status,
        audience_type=b.audience_type,
        total_recipients=b.total_recipients,
        success_count=b.success_count,
        failed_count=b.failed_count,
        blocked_count=b.blocked_count,
        progress_percent=_progress_percent(b),
        created_at=b.created_at,
        started_at=b.started_at,
        completed_at=b.completed_at,
    )
