import uuid
from datetime import datetime
from math import ceil
from typing import Optional

import pytz
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BufferedInputFile
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin.deps import get_current_admin
from app.api.admin.schemas.user_broadcast import (
    AudiencePreviewRequest,
    AudiencePreviewResponse,
    DraftUpdate,
    MediaUploadResponse,
    PaginatedUserBroadcasts,
    TemplateCreate,
    TemplateItem,
    TemplateUpdate,
    UserBroadcastCreate,
    UserBroadcastCreateResponse,
    UserBroadcastHistoryItem,
    UserBroadcastProgress,
)
from app.cache.client import redis_client
from app.cache.keys import CacheKey
from app.core.config import settings
from app.core.logging import get_logger
from app.db.models.user_broadcast import (
    BroadcastTemplate,
    MediaType,
    UserBroadcast,
    UserBroadcastStatus,
)
from app.db.session import get_db_session
from app.repositories.broadcast import BroadcastRepository
from app.repositories.channel import ChannelRepository
from app.repositories.admin_audit_log import AdminAuditLogRepository
from app.repositories.user_broadcast import (
    BroadcastRecurringRuleRepository,
    BroadcastTemplateRepository,
    UserBroadcastRepository,
)
from app.schedulers.jobs.user_broadcast import run_user_broadcast_job
from app.services.broadcast import BroadcastService
from app.services.recurrence import compute_next_run
from app.services.segmentation import (
    SegmentFilter,
    SegmentationService,
    quick_segment_to_filter,
)
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


def _resolve_segment(
    audience_type: Optional[str], filters: Optional[SegmentFilter]
) -> tuple[str, SegmentFilter]:
    """Turn the request (quick audience_type OR advanced filters) into a
    (display_label, SegmentFilter) pair. Filters win when both are present."""
    if filters is not None:
        return "custom", filters
    # audience_type guaranteed present + valid by schema validation.
    return audience_type, quick_segment_to_filter(audience_type)


@router.post("/users/preview", response_model=AudiencePreviewResponse)
async def preview_user_audience(
    body: AudiencePreviewRequest,
    session: AsyncSession = Depends(get_db_session),
    _admin: str = Depends(get_current_admin),
) -> AudiencePreviewResponse:
    """Audience statistics for the resolved segment. Uses the exact same
    SegmentationService the sender uses, so the preview can never drift from
    delivery."""
    _, segment_filter = _resolve_segment(body.audience_type, body.filters)
    engine = SegmentationService(session)
    stats = await engine.stats(segment_filter)
    return AudiencePreviewResponse(**stats)


def _enqueue_send(scheduler, broadcast_id: uuid.UUID, run_date: Optional[datetime] = None) -> None:
    """Register the one-off delivery job (immediate if run_date is None)."""
    kwargs = {"run_date": run_date} if run_date is not None else {}
    scheduler.add_job(
        run_user_broadcast_job,
        "date",
        args=[str(broadcast_id)],
        id=f"user_broadcast:{broadcast_id}",
        replace_existing=True,
        misfire_grace_time=3600,
        **kwargs,
    )


@router.post("/users", response_model=UserBroadcastCreateResponse, status_code=201)
async def create_user_broadcast(
    body: UserBroadcastCreate,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    admin: str = Depends(get_current_admin),
) -> UserBroadcastCreateResponse:
    await _check_rate_limit(admin)

    # ── Template prefill ───────────────────────────────────────────────────
    message, parse_mode = body.message, body.parse_mode
    media_type, media_file_id = body.media_type, body.media_file_id
    if body.template_id is not None:
        tmpl = await BroadcastTemplateRepository(session).get_by_id(body.template_id)
        if tmpl is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
        if not body.message:
            message, parse_mode = tmpl.message, tmpl.parse_mode
        if body.media_type == MediaType.TEXT.value and not body.media_file_id:
            media_type, media_file_id = tmpl.media_type, tmpl.media_file_id

    if media_type != MediaType.TEXT.value and not media_file_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="media_file_id is required for photo/document",
        )

    display_audience, segment_filter = _resolve_segment(body.audience_type, body.filters)
    # For draft/scheduled/recurring the audience is re-resolved at execution, so
    # persist the effective filter (even for quick segments). Immediate sends
    # snapshot now, so only the advanced filter is persisted (Sprint-2 behavior).
    resolved_filter_json = segment_filter.model_dump(mode="json", exclude_none=True) or None
    advanced_filter_json = (
        body.filters.model_dump(mode="json", exclude_none=True) if body.filters else None
    )

    bot = request.app.state.bot
    scheduler = request.app.state.scheduler
    svc = UserBroadcastService(session, bot)
    audit_repo = AdminAuditLogRepository(session)
    ip = request.client.host if request.client else None

    common = dict(
        message=message,
        parse_mode=parse_mode,
        audience_type=display_audience,
        segment_filter=segment_filter,
        media_type=media_type,
        media_file_id=media_file_id,
        template_id=body.template_id,
        created_by=admin,
    )

    # ── Recurring: source is stored as a draft; the dispatcher creates runs ──
    if body.recurrence is not None:
        source = await svc.create_broadcast(
            **common,
            filters_payload=resolved_filter_json,
            status=UserBroadcastStatus.DRAFT.value,
        )
        rec_hour = rec_minute = None
        if body.recurrence.time_of_day:
            rec_hour, rec_minute = (int(p) for p in body.recurrence.time_of_day.split(":"))
        next_run = compute_next_run(
            frequency=body.recurrence.frequency,
            interval=body.recurrence.interval,
            day_of_week=body.recurrence.day_of_week,
            day_of_month=body.recurrence.day_of_month,
            after=datetime.now(TZ),
            hour=rec_hour,
            minute=rec_minute,
        )
        await BroadcastRecurringRuleRepository(session).create(
            broadcast_id=source.id,
            frequency=body.recurrence.frequency,
            interval=body.recurrence.interval,
            day_of_week=body.recurrence.day_of_week,
            day_of_month=body.recurrence.day_of_month,
            next_run_at=next_run,
        )
        await session.commit()
        await audit_repo.log(
            action="user_broadcast_recurring_created", admin_username=admin,
            entity_type="user_broadcast", entity_id=str(source.id),
            details=f"freq={body.recurrence.frequency} interval={body.recurrence.interval} next={next_run}",
            ip_address=ip,
        )
        return _create_response(source)

    # ── Draft: saved, never sent until launched ──────────────────────────────
    if body.save_as_draft:
        broadcast = await svc.create_broadcast(
            **common, filters_payload=resolved_filter_json,
            status=UserBroadcastStatus.DRAFT.value, scheduled_for=body.scheduled_for,
        )
        await audit_repo.log(
            action="user_broadcast_draft_created", admin_username=admin,
            entity_type="user_broadcast", entity_id=str(broadcast.id),
            details=f"audience={display_audience}", ip_address=ip,
        )
        return _create_response(broadcast)

    # ── Scheduled: one-off job at scheduled_for ──────────────────────────────
    if body.scheduled_for is not None:
        broadcast = await svc.create_broadcast(
            **common, filters_payload=resolved_filter_json,
            status=UserBroadcastStatus.SCHEDULED.value, scheduled_for=body.scheduled_for,
        )
        _enqueue_send(scheduler, broadcast.id, run_date=body.scheduled_for)
        await audit_repo.log(
            action="user_broadcast_scheduled", admin_username=admin,
            entity_type="user_broadcast", entity_id=str(broadcast.id),
            details=f"audience={display_audience} when={body.scheduled_for}", ip_address=ip,
        )
        return _create_response(broadcast)

    # ── Immediate (Sprint 1 behavior) ────────────────────────────────────────
    broadcast = await svc.create_broadcast(
        **common, filters_payload=advanced_filter_json,
        status=UserBroadcastStatus.PENDING.value,
    )
    _enqueue_send(scheduler, broadcast.id)
    await audit_repo.log(
        action="user_broadcast_created", admin_username=admin,
        entity_type="user_broadcast", entity_id=str(broadcast.id),
        details=f"audience={display_audience} recipients={broadcast.total_recipients} media={media_type}",
        ip_address=ip,
    )
    return _create_response(broadcast)


def _create_response(b: UserBroadcast) -> UserBroadcastCreateResponse:
    return UserBroadcastCreateResponse(
        id=b.id,
        status=b.status,
        audience_type=b.audience_type,
        total_recipients=b.total_recipients,
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
                media_type=b.media_type,
                total_recipients=b.total_recipients,
                success_count=b.success_count,
                failed_count=b.failed_count,
                blocked_count=b.blocked_count,
                scheduled_for=b.scheduled_for,
                template_id=b.template_id,
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


@router.patch("/users/{broadcast_id}", response_model=UserBroadcastCreateResponse)
async def update_draft(
    broadcast_id: uuid.UUID,
    body: DraftUpdate,
    session: AsyncSession = Depends(get_db_session),
    _admin: str = Depends(get_current_admin),
) -> UserBroadcastCreateResponse:
    repo = UserBroadcastRepository(session)
    b = await repo.get_by_id(broadcast_id)
    if b is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Broadcast not found")
    if b.status != UserBroadcastStatus.DRAFT.value:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only drafts can be edited")

    fields: dict = {}
    if body.message is not None:
        fields["message"] = body.message
    if body.parse_mode is not None:
        fields["parse_mode"] = body.parse_mode
    if body.media_type is not None:
        fields["media_type"] = body.media_type
    if body.media_file_id is not None:
        fields["media_file_id"] = body.media_file_id
    if body.scheduled_for is not None:
        fields["scheduled_for"] = body.scheduled_for
    if body.audience_type is not None or body.filters is not None:
        display, seg = _resolve_segment(body.audience_type, body.filters)
        fields["audience_type"] = display
        fields["filters"] = seg.model_dump(mode="json", exclude_none=True) or None

    await repo.update_draft(broadcast_id, **fields)
    await session.commit()
    updated = await repo.get_by_id(broadcast_id)
    return _create_response(updated)


@router.post("/users/{broadcast_id}/send", response_model=UserBroadcastCreateResponse)
async def send_draft(
    broadcast_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    admin: str = Depends(get_current_admin),
) -> UserBroadcastCreateResponse:
    await _check_rate_limit(admin)
    repo = UserBroadcastRepository(session)
    b = await repo.get_by_id(broadcast_id)
    if b is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Broadcast not found")
    if b.status != UserBroadcastStatus.DRAFT.value:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only drafts can be sent")

    svc = UserBroadcastService(session, request.app.state.bot)
    await svc.launch_draft_now(b)
    _enqueue_send(request.app.state.scheduler, broadcast_id)

    refreshed = await repo.get_by_id(broadcast_id)
    return _create_response(refreshed)


# ── Templates ────────────────────────────────────────────────────────────────

def _template_item(t: BroadcastTemplate) -> TemplateItem:
    return TemplateItem(
        id=t.id,
        name=t.name,
        description=t.description,
        message=t.message,
        parse_mode=t.parse_mode,
        media_type=t.media_type,
        media_file_id=t.media_file_id,
        created_at=t.created_at,
        updated_at=t.updated_at,
    )


@router.get("/templates", response_model=list[TemplateItem])
async def list_templates(
    session: AsyncSession = Depends(get_db_session),
    _admin: str = Depends(get_current_admin),
) -> list[TemplateItem]:
    rows = await BroadcastTemplateRepository(session).list_all()
    return [_template_item(t) for t in rows]


@router.post("/templates", response_model=TemplateItem, status_code=201)
async def create_template(
    body: TemplateCreate,
    session: AsyncSession = Depends(get_db_session),
    _admin: str = Depends(get_current_admin),
) -> TemplateItem:
    repo = BroadcastTemplateRepository(session)
    t = await repo.create(
        name=body.name,
        description=body.description,
        message=body.message,
        parse_mode=body.parse_mode,
        media_type=body.media_type,
        media_file_id=body.media_file_id,
    )
    await session.commit()
    return _template_item(t)


@router.put("/templates/{template_id}", response_model=TemplateItem)
async def update_template(
    template_id: uuid.UUID,
    body: TemplateUpdate,
    session: AsyncSession = Depends(get_db_session),
    _admin: str = Depends(get_current_admin),
) -> TemplateItem:
    repo = BroadcastTemplateRepository(session)
    existing = await repo.get_by_id(template_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    t = await repo.update(template_id, **body.model_dump(exclude_none=True))
    await session.commit()
    return _template_item(t)


@router.delete("/templates/{template_id}", status_code=204)
async def delete_template(
    template_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    _admin: str = Depends(get_current_admin),
) -> None:
    repo = BroadcastTemplateRepository(session)
    existing = await repo.get_by_id(template_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    await repo.delete(existing)
    await session.commit()


# ── Media upload (returns a reusable Telegram file_id; no binaries stored) ────

@router.post("/media", response_model=MediaUploadResponse)
async def upload_media(
    request: Request,
    media_type: str = Form(...),
    file: UploadFile = File(...),
    _admin: str = Depends(get_current_admin),
) -> MediaUploadResponse:
    if media_type not in (MediaType.PHOTO.value, MediaType.DOCUMENT.value):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="media_type must be photo or document",
        )
    storage_chat = settings.MEDIA_STORAGE_CHAT_ID
    if storage_chat is None:
        admins = settings.admin_id_list
        storage_chat = admins[0] if admins else None
    if storage_chat is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No media storage chat configured (set MEDIA_STORAGE_CHAT_ID or ADMIN_IDS)",
        )

    content = await file.read()
    upload = BufferedInputFile(content, filename=file.filename or "upload")
    bot = request.app.state.bot
    try:
        if media_type == MediaType.PHOTO.value:
            msg = await bot.send_photo(chat_id=storage_chat, photo=upload)
            file_id = msg.photo[-1].file_id
        else:
            msg = await bot.send_document(chat_id=storage_chat, document=upload)
            file_id = msg.document.file_id
    except TelegramAPIError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Telegram upload failed: {exc}",
        )
    # The send above only exists to mint a reusable file_id; the file_id stays
    # valid after the message is deleted, so remove it to avoid leaving the
    # uploaded media visible in the storage chat (often an admin's own DM).
    try:
        await bot.delete_message(chat_id=storage_chat, message_id=msg.message_id)
    except TelegramAPIError:
        pass
    return MediaUploadResponse(media_type=media_type, media_file_id=file_id)


# ── Recurring rules ────────────────────────────────────────────────────────--

@router.get("/recurring")
async def list_recurring_rules(
    session: AsyncSession = Depends(get_db_session),
    _admin: str = Depends(get_current_admin),
) -> list[dict]:
    rules = await BroadcastRecurringRuleRepository(session).list_all()
    bcast_repo = UserBroadcastRepository(session)
    items: list[dict] = []
    for r in rules:
        source = await bcast_repo.get_by_id(r.broadcast_id)
        next_local = r.next_run_at.astimezone(TZ)
        items.append(
            {
                "id": str(r.id),
                "broadcast_id": str(r.broadcast_id),
                "frequency": r.frequency,
                "interval": r.interval,
                "day_of_week": r.day_of_week,
                "day_of_month": r.day_of_month,
                "time_of_day": next_local.strftime("%H:%M"),
                "next_run_at": r.next_run_at.isoformat(),
                "is_active": r.is_active,
                "message_preview": (source.message[:80] if source and source.message else ""),
                "media_type": (source.media_type if source else "text"),
                "audience_type": (source.audience_type if source else ""),
            }
        )
    return items


@router.delete("/recurring/{rule_id}", status_code=204)
async def deactivate_recurring_rule(
    rule_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    _admin: str = Depends(get_current_admin),
) -> None:
    repo = BroadcastRecurringRuleRepository(session)
    rule = await repo.get_by_id(rule_id)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    await repo.set_active(rule_id, False)
    await session.commit()
