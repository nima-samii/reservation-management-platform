import csv
import io
import json
import uuid
from datetime import date, datetime
from math import ceil
from typing import Optional

import pytz
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.api.admin.deps import get_current_admin
from app.api.admin.schemas.reservations import (
    AttendanceResponse,
    CancelReservationBody,
    CreateReservationBody,
    DaySummary,
    NoShowResponse,
    PaginatedReservations,
    RecordAttendanceBody,
    ReservationDetail,
    ReservationItem,
    SlotInfo,
    ChannelInfo,
    UserInfo,
    CountryInfo,
)
from app.cache.client import redis_client
from app.core.config import settings
from app.core.exceptions import (
    AttendanceAlreadyRecordedError,
    AttendanceNotDecidableError,
    DailyLimitError,
    DuplicateSlotTimeError,
    LegacyNoShowRecordedError,
    MaxReservationsError,
    NotFoundError,
    PastSlotError,
    ReservationNotCancellableError,
    SameDayCutoffError,
    SlotUnavailableError,
    UserBannedError,
    ValidationError,
)
from app.core.logging import get_logger
from app.db.models.reservation import Reservation, ReservationStatus
from app.db.session import get_db_session
from app.repositories.admin_audit_log import AdminAuditLogRepository
from app.repositories.reservation import (
    ATTENDANCE_FILTERS,
    ReservationRepository,
    _parse_notes,
)
from app.repositories.slot import SlotRepository
from app.schedulers.jobs.score_notification import enqueue_score_notification
from app.services.reservation import ReservationService
from app.services.reservation_timeline import ReservationTimelineService, TimelineEvent
from app.services.score import ParticipationScoreService

router = APIRouter(tags=["admin-reservations"])
logger = get_logger(__name__)

TZ = pytz.timezone(settings.TIMEZONE)

_VALID_STATUS = {s.value for s in ReservationStatus}
_VALID_ATTENDANCE = set(ATTENDANCE_FILTERS)


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reservation not found")


def _check_attendance_filter(value: Optional[str]) -> None:
    """Reject an unknown attendance filter instead of ignoring it.

    Silently dropping it would return an unfiltered page that looks like a
    filtered one — the worst outcome for a queue view an admin works through.
    """
    if value and value not in _VALID_ATTENDANCE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid attendance filter. Valid: {sorted(_VALID_ATTENDANCE)}",
        )


def _to_item(res: Reservation) -> ReservationItem:
    slot = res.slot
    slot_local = slot.slot_datetime.astimezone(TZ)
    user = res.user
    country = (
        CountryInfo(
            name=user.country_rel.name,
            flag_emoji=user.country_rel.flag_emoji,
        )
        if user.country_rel
        else None
    )
    return ReservationItem(
        id=res.id,
        status=res.status,
        notes=res.notes,
        slot=SlotInfo(
            id=slot.id,
            slot_datetime=slot.slot_datetime,
            slot_time_local=slot_local.strftime("%H:%M"),
        ),
        channel=ChannelInfo(id=res.channel.id, name=res.channel.name),
        user=UserInfo(
            id=user.id,
            public_user_code=user.public_user_code,
            full_name=user.full_name,
            gender=user.gender,
            country=country,
            participation_score=user.participation_score,
        ),
        no_show_applied=_parse_notes(res.notes).get("no_show_penalty_applied") is True,
        attendance_status=res.attendance_status,
        attendance_score_delta=res.attendance_score_delta,
        attendance_reason=res.attendance_reason,
        attendance_marked_by=res.attendance_marked_by,
        attendance_marked_at=res.attendance_marked_at,
    )


def _today_local() -> date:
    return datetime.now(TZ).date()


# ── GET /export must be declared BEFORE /{reservation_id} ─────────────────────

@router.get("/export")
async def export_reservations(
    date_from: date = Query(...),
    date_to: date = Query(...),
    channel_id: Optional[uuid.UUID] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    attendance: Optional[str] = Query(None),
    format: str = Query("csv"),
    session: AsyncSession = Depends(get_db_session),
    _admin: str = Depends(get_current_admin),
) -> StreamingResponse:
    if (date_to - date_from).days > 90:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Export range must not exceed 90 days",
        )
    if status_filter and status_filter not in _VALID_STATUS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid status. Valid: {sorted(_VALID_STATUS)}",
        )
    _check_attendance_filter(attendance)

    repo = ReservationRepository(session)
    rows = await repo.admin_export(
        date_from=date_from,
        date_to=date_to,
        channel_id=channel_id,
        status=status_filter,
        attendance=attendance,
    )

    items = [_to_item(r) for r in rows]

    if format == "json":
        import json as _json
        content = _json.dumps([i.model_dump(mode="json") for i in items], indent=2)
        return StreamingResponse(
            iter([content]),
            media_type="application/json",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="reservations_{date_from}_{date_to}.json"'
                )
            },
        )

    # CSV
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "reservation_id",
        "slot_datetime",
        "slot_time_local",
        "channel_name",
        "user_public_code",
        "user_full_name",
        "country",
        "gender",
        "score_at_export",
        "status",
        # Appended, not inserted: existing consumers read this file by column
        # position as often as by header.
        "no_show_applied",
        "attendance_status",
        "attendance_score",
        "attendance_reason",
        "attendance_marked_by",
        "attendance_marked_at",
    ])
    for item in items:
        country_str = ""
        if item.user.country:
            flag = item.user.country.flag_emoji or ""
            country_str = f"{flag} {item.user.country.name}".strip()
        writer.writerow([
            str(item.id),
            item.slot.slot_datetime.astimezone(TZ).isoformat(),
            item.slot.slot_time_local,
            item.channel.name,
            item.user.public_user_code,
            item.user.full_name,
            country_str,
            item.user.gender or "",
            item.user.participation_score,
            item.status,
            str(item.no_show_applied).lower(),
            item.attendance_status or "",
            # Written out explicitly rather than with `or ""`, which would turn
            # a real decision of 0 points into a blank cell — the one value
            # this feature exists to make expressible.
            "" if item.attendance_score_delta is None else item.attendance_score_delta,
            item.attendance_reason or "",
            item.attendance_marked_by or "",
            item.attendance_marked_at.astimezone(TZ).isoformat()
            if item.attendance_marked_at
            else "",
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                f'attachment; filename="reservations_{date_from}_{date_to}.csv"'
            )
        },
    )


# ── GET /available-slots must be declared BEFORE /{reservation_id} ────────────

@router.get("/available-slots", response_model=list[SlotInfo])
async def list_available_slots(
    channel_id: uuid.UUID = Query(...),
    date_param: date = Query(..., alias="date"),
    session: AsyncSession = Depends(get_db_session),
    _admin: str = Depends(get_current_admin),
) -> list[SlotInfo]:
    """Open (un-booked, future) slots for a channel on a date — for the admin
    Create-Reservation slot picker.

    Unlike the user-facing flow this is NOT subject to the channel-unlock
    capacity threshold: an admin picks an explicit channel and should see every
    open slot on it. The same-day cutoff is still enforced at booking time by
    the shared booking core, so a same-day slot shown here may still be rejected
    on submit (surfaced as a clear error)."""
    repo = SlotRepository(session)
    now = datetime.now(TZ)
    slots = await repo.get_available_slots_for_date_and_channel(
        date_param, channel_id, now
    )
    return [
        SlotInfo(
            id=slot.id,
            slot_datetime=slot.slot_datetime,
            slot_time_local=slot.slot_datetime.astimezone(TZ).strftime("%H:%M"),
        )
        for slot in slots
    ]


@router.get("", response_model=PaginatedReservations)
async def list_reservations(
    date_param: Optional[date] = Query(None, alias="date"),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    channel_id: Optional[uuid.UUID] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    attendance: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    session: AsyncSession = Depends(get_db_session),
    _admin: str = Depends(get_current_admin),
) -> PaginatedReservations:
    """One page of reservations, plus the counts the filter bar shows.

    `attendance` narrows the page to a stage of the attendance decision:
    `pending` (the queue — completed and unjudged), `decided`, `attended` or
    `absent`. The summary counts ignore it on purpose; they are the totals the
    filters are pressed against.
    """
    if status_filter and status_filter not in _VALID_STATUS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid status. Valid: {sorted(_VALID_STATUS)}",
        )
    _check_attendance_filter(attendance)

    # Default to today when no date args supplied
    date_single = date_param
    if date_single is None and date_from is None and date_to is None:
        date_single = _today_local()

    repo = ReservationRepository(session)

    rows, total = await repo.admin_list(
        date_single=date_single,
        date_from=date_from,
        date_to=date_to,
        channel_id=channel_id,
        status=status_filter,
        search=search,
        attendance=attendance,
        page=page,
        page_size=page_size,
    )

    summary_dict = await repo.admin_summary(
        date_single=date_single,
        date_from=date_from,
        date_to=date_to,
        channel_id=channel_id,
        search=search,
    )

    return PaginatedReservations(
        items=[_to_item(r) for r in rows],
        total=total,
        page=page,
        pages=max(1, ceil(total / page_size)),
        summary=DaySummary(**summary_dict),
    )


@router.post("", response_model=ReservationDetail, status_code=status.HTTP_201_CREATED)
async def create_reservation(
    body: CreateReservationBody,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    admin: str = Depends(get_current_admin),
) -> ReservationDetail:
    """Admin-create a reservation for an existing user.

    Goes through the same booking core as user booking — identical validation
    (daily limit, max active, duplicate time, double-booking, past-slot,
    same-day cutoff). Booking does not change the score; that happens when an
    admin records attendance afterwards. Banned users are rejected. A
    confirmation DM is sent to the user out-of-band after this request commits.
    """
    svc = ReservationService(session, redis_client)
    try:
        reservation = await svc.admin_create_reservation(
            user_id=body.user_id, slot_id=body.slot_id, actor=admin
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message)
    except UserBannedError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message)
    except (
        DailyLimitError,
        DuplicateSlotTimeError,
        MaxReservationsError,
        SlotUnavailableError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message)
    except (PastSlotError, SameDayCutoffError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message)

    audit_repo = AdminAuditLogRepository(session)
    ip = request.client.host if request.client else None
    await audit_repo.log(
        action="reservation_created_by_admin",
        admin_username=admin,
        entity_type="reservation",
        entity_id=str(reservation.id),
        details=f"user_id={body.user_id} slot_id={body.slot_id}",
        ip_address=ip,
    )
    logger.info(
        "admin_reservation_created",
        reservation_id=str(reservation.id),
        admin=admin,
    )

    # Re-load with country eager-loaded so the detail response serializes cleanly.
    detail = await ReservationRepository(session).get_reservation_admin_detail(reservation.id)
    return ReservationDetail(**_to_item(detail or reservation).model_dump())


@router.get("/{reservation_id}", response_model=ReservationDetail)
async def get_reservation(
    reservation_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    _admin: str = Depends(get_current_admin),
) -> ReservationDetail:
    repo = ReservationRepository(session)
    res = await repo.get_reservation_admin_detail(reservation_id)
    if not res:
        raise _not_found()
    return ReservationDetail(**_to_item(res).model_dump())


@router.get("/{reservation_id}/timeline", response_model=list[TimelineEvent])
async def get_reservation_timeline(
    reservation_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    _admin: str = Depends(get_current_admin),
) -> list[TimelineEvent]:
    """Read-only chronological timeline for a reservation, oldest first.

    Built on the fly from existing data (reservation, score ledger,
    notification logs, admin audit logs) — no timeline persistence. Returns an
    empty array when the reservation has no derivable events beyond creation.
    """
    svc = ReservationTimelineService(session)
    try:
        return await svc.build(reservation_id)
    except NotFoundError:
        raise _not_found()


@router.post("/{reservation_id}/cancel", response_model=ReservationDetail)
async def cancel_reservation(
    reservation_id: uuid.UUID,
    body: CancelReservationBody,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    admin: str = Depends(get_current_admin),
) -> ReservationDetail:
    """Admin-cancel an ACTIVE reservation, audit the action, and notify the user.

    No score penalty is applied (operational action). The user DM is sent
    out-of-band after this request commits and cannot roll the cancellation back.
    """
    svc = ReservationService(session, redis_client)
    try:
        res = await svc.admin_cancel_reservation(
            reservation_id, actor=admin, reason=body.reason
        )
    except NotFoundError:
        raise _not_found()
    except ReservationNotCancellableError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message)

    audit_repo = AdminAuditLogRepository(session)
    ip = request.client.host if request.client else None
    await audit_repo.log(
        action="reservation_cancelled_by_admin",
        admin_username=admin,
        entity_type="reservation",
        entity_id=str(reservation_id),
        details=f"reason={body.reason!r}",
        ip_address=ip,
    )
    logger.info(
        "admin_reservation_cancelled",
        reservation_id=str(reservation_id),
        admin=admin,
    )

    # Re-load with country eager-loaded so the detail response serializes cleanly.
    detail = await ReservationRepository(session).get_reservation_admin_detail(reservation_id)
    return ReservationDetail(**_to_item(detail or res).model_dump())


@router.post("/{reservation_id}/attendance", response_model=AttendanceResponse)
async def record_attendance(
    reservation_id: uuid.UUID,
    body: RecordAttendanceBody,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    admin: str = Depends(get_current_admin),
) -> AttendanceResponse:
    """Record whether a completed reservation was attended, and what it scored.

    Replaces `POST /{id}/no-show`. The outcome and the score are independent:
    the admin decides both, and no combination is rejected — an attended
    session may be worth nothing and an absence may still be worth points. The
    reason is required because it is quoted back to the user in the DM that
    follows.

    At most one decision per reservation, enforced by a conditional UPDATE
    rather than a read-then-write, and applied before the score so a failure
    can never leave a charge without a decision.

    409 covers the three ways a reservation can be undecidable, and they are
    worth telling apart in the message: it is not COMPLETED yet (a session
    whose slot has just passed stays ACTIVE until the lifecycle job runs at
    :00/:30 — the admin has to wait, not retry differently), a decision already
    exists, or the legacy no-show penalty already scored this session.
    """
    svc = ReservationService(session, redis_client)
    try:
        outcome = await svc.record_attendance(
            reservation_id,
            attendance_status=body.attendance_status,
            score_delta=body.score_delta,
            reason=body.reason,
            actor=admin,
        )
    except NotFoundError:
        raise _not_found()
    except (
        AttendanceAlreadyRecordedError,
        AttendanceNotDecidableError,
        LegacyNoShowRecordedError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message)
    except ValidationError as exc:
        # The request schema enforces the same bounds, so this is reachable only
        # if the two ever drift — the service is the authority either way.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message
        )

    audit_repo = AdminAuditLogRepository(session)
    ip = request.client.host if request.client else None
    await audit_repo.log(
        action="attendance_recorded",
        admin_username=admin,
        entity_type="reservation",
        entity_id=str(reservation_id),
        details=(
            f"status={outcome.attendance_status} "
            f"score_delta={outcome.score_delta:+d} "
            f"reason={outcome.reason!r} tx_id={outcome.transaction_id}"
        ),
        ip_address=ip,
    )
    logger.info(
        "admin_attendance_recorded",
        reservation_id=str(reservation_id),
        attendance_status=outcome.attendance_status,
        score_delta=outcome.score_delta,
        admin=admin,
    )

    return AttendanceResponse(
        reservation_id=outcome.reservation.id,
        user_id=outcome.reservation.user_id,
        attendance_status=outcome.attendance_status,
        score_delta=outcome.score_delta,
        reason=outcome.reason,
        new_score=outcome.new_score,
        transaction_id=outcome.transaction_id,
        marked_by=outcome.reservation.attendance_marked_by,
        marked_at=outcome.reservation.attendance_marked_at,
    )


@router.post(
    "/{reservation_id}/no-show", response_model=NoShowResponse, deprecated=True
)
async def mark_no_show(
    reservation_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    admin: str = Depends(get_current_admin),
) -> NoShowResponse:
    """Deprecated — use `POST /{id}/attendance` instead.

    Kept alive only because the shipped admin panel still calls it; the
    replacement records the outcome and the score as separate decisions instead
    of hardcoding -1, and does it atomically.

    Two known defects, which are why it is not being extended: the penalty is
    applied *before* the flag that records it is written, so a crash in between
    charges the user for a decision no later request can see was already made;
    and there is no lock or conditional update, so two concurrent requests both
    read an unflagged row and both charge.
    """
    repo = ReservationRepository(session)
    audit_repo = AdminAuditLogRepository(session)

    res = await repo.get_reservation_admin_detail(reservation_id)
    if not res:
        raise _not_found()

    if res.status != ReservationStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No-show can only be applied to completed reservations",
        )

    # The new attendance decision already scored this session. Mirrors the
    # guard record_attendance makes in the other direction, so the two systems
    # cannot both charge one reservation during the changeover.
    if res.attendance_status is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "An attendance decision has already been recorded for this "
                "reservation; use the attendance endpoint to see it."
            ),
        )

    notes_dict = _parse_notes(res.notes)
    if notes_dict.get("no_show_penalty_applied") is True:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No-show penalty already applied for this reservation",
        )

    # Apply score penalty
    score_svc = ParticipationScoreService(session)
    tx = await score_svc.apply_no_show_penalty(
        user_id=res.user_id,
        reservation_id=res.id,
        reason="No-show penalty applied by admin",
    )

    # Merge flag into notes JSON
    notes_dict["no_show_penalty_applied"] = True
    res.notes = json.dumps(notes_dict)
    await repo.save(res)

    # Refresh user to get updated score
    await session.refresh(res.user)

    ip = request.client.host if request.client else None
    await audit_repo.log(
        action="no_show_applied",
        admin_username=admin,
        entity_type="reservation",
        entity_id=str(reservation_id),
        details=f"user_id={res.user_id} tx_id={tx.id}",
        ip_address=ip,
    )
    logger.info(
        "admin_no_show_applied",
        reservation_id=str(reservation_id),
        user_id=str(res.user_id),
        admin=admin,
    )

    # Out-of-band DM (delayed job runs after this request's commit lands).
    enqueue_score_notification(tx.id, tx.transaction_type)

    return NoShowResponse(
        reservation_id=res.id,
        user_id=res.user_id,
        new_score=res.user.participation_score,
        transaction_id=tx.id,
    )
