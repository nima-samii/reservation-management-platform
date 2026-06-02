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
from app.cache.client import redis_client
from app.cache.keys import CacheKey
from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import get_db_session
from app.repositories.broadcast import BroadcastRepository
from app.repositories.channel import ChannelRepository
from app.repositories.admin_audit_log import AdminAuditLogRepository
from app.services.broadcast import BroadcastService

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
