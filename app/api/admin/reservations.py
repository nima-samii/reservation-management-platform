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
    DaySummary,
    NoShowResponse,
    PaginatedReservations,
    ReservationDetail,
    ReservationItem,
    SlotInfo,
    ChannelInfo,
    UserInfo,
    CountryInfo,
)
from app.core.config import settings
from app.core.logging import get_logger
from app.db.models.reservation import Reservation, ReservationStatus
from app.db.session import get_db_session
from app.repositories.admin_audit_log import AdminAuditLogRepository
from app.repositories.reservation import ReservationRepository, _parse_notes
from app.services.score import ParticipationScoreService

router = APIRouter(tags=["admin-reservations"])
logger = get_logger(__name__)

TZ = pytz.timezone(settings.TIMEZONE)

_VALID_STATUS = {s.value for s in ReservationStatus}


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reservation not found")


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

    repo = ReservationRepository(session)
    rows = await repo.admin_export(
        date_from=date_from,
        date_to=date_to,
        channel_id=channel_id,
        status=status_filter,
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
        "no_show_applied",
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


@router.get("", response_model=PaginatedReservations)
async def list_reservations(
    date_param: Optional[date] = Query(None, alias="date"),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    channel_id: Optional[uuid.UUID] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    session: AsyncSession = Depends(get_db_session),
    _admin: str = Depends(get_current_admin),
) -> PaginatedReservations:
    if status_filter and status_filter not in _VALID_STATUS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid status. Valid: {sorted(_VALID_STATUS)}",
        )

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


@router.post("/{reservation_id}/no-show", response_model=NoShowResponse)
async def mark_no_show(
    reservation_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    admin: str = Depends(get_current_admin),
) -> NoShowResponse:
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

    return NoShowResponse(
        reservation_id=res.id,
        user_id=res.user_id,
        new_score=res.user.participation_score,
        transaction_id=tx.id,
    )
