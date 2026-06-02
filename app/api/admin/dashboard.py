import json
from datetime import date, datetime, timedelta

import pytz
import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin.deps import get_current_admin
from app.cache.client import redis_client
from app.cache.keys import CacheKey
from app.core.config import settings
from app.db.models.broadcast_log import BroadcastLog
from app.db.models.channel import Channel
from app.db.models.country import Country
from app.db.models.reservation import Reservation, ReservationStatus
from app.db.models.slot import ReservationSlot
from app.db.models.user import User
from app.db.session import get_db_session
from app.repositories.reservation import _parse_notes

router = APIRouter(tags=["admin-dashboard"])
TZ = pytz.timezone(settings.TIMEZONE)


def _today_local() -> date:
    return datetime.now(TZ).date()


def _local_date_expr():
    return sa.cast(
        sa.func.timezone(settings.TIMEZONE, ReservationSlot.slot_datetime),
        sa.Date,
    )


@router.get("/stats")
async def get_dashboard_stats(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    _admin: str = Depends(get_current_admin),
) -> dict:
    cached = await redis_client.get(CacheKey.admin_dashboard_stats())
    if cached:
        return json.loads(cached)

    today = _today_local()
    week_start = today - timedelta(days=6)
    local_dt = _local_date_expr()

    # ── Today's reservations ──────────────────────────────────────────────
    today_rows = list(
        (
            await session.execute(
                select(Reservation.status, Reservation.notes, Reservation.user_id)
                .join(Reservation.slot)
                .where(local_dt == today)
            )
        ).all()
    )

    today_active = sum(1 for r in today_rows if r.status == ReservationStatus.ACTIVE)
    today_completed = sum(1 for r in today_rows if r.status == ReservationStatus.COMPLETED)
    today_cancelled = sum(1 for r in today_rows if r.status == ReservationStatus.CANCELLED)
    today_no_show = sum(
        1 for r in today_rows
        if _parse_notes(r.notes).get("no_show_penalty_applied") is True
    )
    today_unique_users = len({r.user_id for r in today_rows})

    slots_generated = (
        await session.execute(
            select(func.count(ReservationSlot.id)).where(
                sa.cast(
                    sa.func.timezone(settings.TIMEZONE, ReservationSlot.slot_datetime),
                    sa.Date,
                ) == today
            )
        )
    ).scalar() or 0

    # ── Fill rate per channel ─────────────────────────────────────────────
    channels = list(
        (
            await session.execute(select(Channel).where(Channel.is_active.is_(True)))
        ).scalars().all()
    )
    fill_rate_list = []
    for ch in channels:
        booked = (
            await session.execute(
                select(func.count(Reservation.id))
                .join(Reservation.slot)
                .where(
                    Reservation.channel_id == ch.id,
                    Reservation.status == ReservationStatus.ACTIVE,
                    local_dt == today,
                )
            )
        ).scalar() or 0
        fill_pct = round(booked / ch.capacity, 4) if ch.capacity > 0 else 0.0
        fill_rate_list.append(
            {
                "channel_id": str(ch.id),
                "channel_name": ch.name,
                "capacity": ch.capacity,
                "booked": booked,
                "fill_pct": fill_pct,
            }
        )

    # ── Week reservations ─────────────────────────────────────────────────
    week_rows = list(
        (
            await session.execute(
                select(Reservation.status, Reservation.notes, Reservation.user_id)
                .join(Reservation.slot)
                .where(local_dt >= week_start, local_dt <= today)
            )
        ).all()
    )
    week_total = len(week_rows)
    week_no_show = sum(
        1 for r in week_rows
        if _parse_notes(r.notes).get("no_show_penalty_applied") is True
    )

    week_start_utc = TZ.localize(
        datetime(week_start.year, week_start.month, week_start.day, 0, 0, 0)
    ).astimezone(pytz.UTC)

    new_users = (
        await session.execute(
            select(func.count(User.id)).where(User.created_at >= week_start_utc)
        )
    ).scalar() or 0

    top_countries_rows = (
        await session.execute(
            select(Country.name, Country.flag_emoji, func.count(User.id).label("cnt"))
            .join(User.country_rel)
            .where(User.created_at >= week_start_utc, User.country_id.is_not(None))
            .group_by(Country.id, Country.name, Country.flag_emoji)
            .order_by(func.count(User.id).desc())
            .limit(5)
        )
    ).all()
    top_countries = [
        {"country_name": r.name, "flag_emoji": r.flag_emoji, "count": r.cnt}
        for r in top_countries_rows
    ]

    # ── System status ─────────────────────────────────────────────────────
    scheduler = getattr(request.app.state, "scheduler", None)
    scheduler_running = bool(scheduler and scheduler.running)

    try:
        await redis_client.client.ping()
        redis_connected = True
    except Exception:
        redis_connected = False

    try:
        await session.execute(select(sa.literal(1)))
        db_connected = True
    except Exception:
        db_connected = False

    last_broadcast = (
        await session.execute(
            select(BroadcastLog).order_by(BroadcastLog.sent_at.desc()).limit(1)
        )
    ).scalars().first()

    result = {
        "today": {
            "total_reservations": len(today_rows),
            "active": today_active,
            "completed": today_completed,
            "cancelled": today_cancelled,
            "no_show": today_no_show,
            "unique_users": today_unique_users,
            "slots_generated": slots_generated,
            "fill_rate_per_channel": fill_rate_list,
        },
        "week": {
            "total_reservations": week_total,
            "no_show_count": week_no_show,
            "no_show_rate": round(week_no_show / week_total, 4) if week_total > 0 else 0.0,
            "new_users": new_users,
            "top_countries": top_countries,
        },
        "system": {
            "scheduler_running": scheduler_running,
            "redis_connected": redis_connected,
            "db_connected": db_connected,
            "last_broadcast_at": last_broadcast.sent_at.isoformat() if last_broadcast else None,
            "last_broadcast_status": last_broadcast.status if last_broadcast else None,
        },
        "_cached_at": datetime.now(TZ).isoformat(),
    }

    await redis_client.set(CacheKey.admin_dashboard_stats(), json.dumps(result), ttl=60)
    return result


@router.get("/activity")
async def get_dashboard_activity(
    days: int = Query(7, ge=1, le=30),
    session: AsyncSession = Depends(get_db_session),
    _admin: str = Depends(get_current_admin),
) -> list[dict]:
    today = _today_local()
    date_start = today - timedelta(days=days - 1)
    local_dt = _local_date_expr()

    rows = (
        await session.execute(
            select(local_dt.label("res_date"), Reservation.status, Reservation.notes)
            .join(Reservation.slot)
            .where(local_dt >= date_start, local_dt <= today)
        )
    ).all()

    day_map: dict[str, dict] = {}
    cursor = date_start
    while cursor <= today:
        day_map[cursor.isoformat()] = {
            "date": cursor.isoformat(),
            "total": 0,
            "completed": 0,
            "cancelled": 0,
            "no_show": 0,
        }
        cursor += timedelta(days=1)

    for row in rows:
        d = row.res_date.isoformat() if hasattr(row.res_date, "isoformat") else str(row.res_date)
        if d not in day_map:
            continue
        day_map[d]["total"] += 1
        if row.status == ReservationStatus.COMPLETED:
            day_map[d]["completed"] += 1
        elif row.status == ReservationStatus.CANCELLED:
            day_map[d]["cancelled"] += 1
        if _parse_notes(row.notes).get("no_show_penalty_applied") is True:
            day_map[d]["no_show"] += 1

    return list(day_map.values())
