import json
from datetime import datetime
from typing import Any

import pytz
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.admin.deps import get_current_admin
from app.cache.client import redis_client
from app.cache.keys import CacheKey
from app.core.config import save_settings_override, settings

router = APIRouter(tags=["admin-settings"])
TZ = pytz.timezone(settings.TIMEZONE)

# ── Field registry ────────────────────────────────────────────────────────────
# Each entry: settings_key -> (category, json_key, type, min, max)
# min/max=None means no numeric range validation

_FIELD_MAP: list[tuple[str, str, str, type, Any, Any]] = [
    # reservation_rules
    ("MAX_ACTIVE_RESERVATIONS",       "reservation_rules", "max_active_reservations",       int,   1,    50),
    ("MAX_RESERVATION_DAYS_AHEAD",    "reservation_rules", "max_reservation_days_ahead",    int,   1,    60),
    ("CHANNEL_CAPACITY_THRESHOLD",    "reservation_rules", "channel_capacity_threshold",    float, 0.1,  1.0),
    ("SAME_DAY_CUTOFF_HOUR",          "reservation_rules", "same_day_cutoff_hour",          int,   0,    23),
    ("SAME_DAY_CANCEL_CUTOFF_HOUR",   "reservation_rules", "same_day_cancel_cutoff_hour",   int,   0,    23),
    # slot_schedule
    ("SLOT_START_HOUR",               "slot_schedule",     "slot_start_hour",               int,   0,    23),
    ("SLOT_END_HOUR",                 "slot_schedule",     "slot_end_hour",                 int,   0,    24),
    ("SLOT_DURATION_MINUTES",         "slot_schedule",     "slot_duration_minutes",         int,   5,    120),
    ("ENABLE_FINAL_MIDNIGHT_SLOT",    "slot_schedule",     "enable_final_midnight_slot",    bool,  None, None),
    ("FINAL_SLOT_TIME",               "slot_schedule",     "final_slot_time",               str,   None, None),
    # notifications
    ("SAME_DAY_REMINDER_HOUR",        "notifications",     "same_day_reminder_hour",        int,   0,    23),
    ("PRE_SESSION_REMINDER_MINUTES",  "notifications",     "pre_session_reminder_minutes",  int,   5,    180),
    # broadcast
    ("DAILY_BROADCAST_HOUR",          "broadcast",         "daily_broadcast_hour",          int,   0,    23),
    ("ENABLE_BROADCAST_AUTO_PIN",     "broadcast",         "enable_broadcast_auto_pin",     bool,  None, None),
    ("DELETE_PREVIOUS_BROADCAST",     "broadcast",         "delete_previous_broadcast",     bool,  None, None),
]

# Lookup maps built once at module load
_KEY_TO_META: dict[str, tuple] = {row[2]: row for row in _FIELD_MAP}   # json_key → row
_SETTINGS_TO_JSON: dict[str, str] = {row[0]: row[2] for row in _FIELD_MAP}


def _build_response() -> dict:
    result: dict[str, dict] = {
        "reservation_rules": {},
        "slot_schedule": {},
        "notifications": {},
        "broadcast": {},
    }
    for settings_key, category, json_key, *_ in _FIELD_MAP:
        result[category][json_key] = getattr(settings, settings_key)
    return result


class SettingsPatchBody(BaseModel):
    reservation_rules: dict[str, Any] | None = None
    slot_schedule: dict[str, Any] | None = None
    notifications: dict[str, Any] | None = None
    broadcast: dict[str, Any] | None = None


@router.get("")
async def get_settings_endpoint(
    _admin: str = Depends(get_current_admin),
) -> dict:
    return _build_response()


@router.patch("")
async def patch_settings(
    body: SettingsPatchBody,
    admin: str = Depends(get_current_admin),
) -> dict:
    incoming: dict[str, Any] = {}
    for section_name in ("reservation_rules", "slot_schedule", "notifications", "broadcast"):
        section = getattr(body, section_name) or {}
        for json_key, value in section.items():
            if json_key not in _KEY_TO_META:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Unknown setting: {json_key}",
                )
            _, _, _, expected_type, min_val, max_val = _KEY_TO_META[json_key]
            # Type coercion
            try:
                if expected_type is bool:
                    value = bool(value)
                elif expected_type is int:
                    value = int(value)
                elif expected_type is float:
                    value = float(value)
                else:
                    value = str(value)
            except (ValueError, TypeError):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"{json_key}: expected {expected_type.__name__}",
                )
            # Range validation
            if min_val is not None and value < min_val:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"{json_key}: minimum value is {min_val}",
                )
            if max_val is not None and value > max_val:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"{json_key}: maximum value is {max_val}",
                )
            incoming[json_key] = value

    if not incoming:
        return _build_response()

    # Capture old values for history
    history_entries = []
    now_iso = datetime.now(TZ).isoformat()
    for json_key, new_value in incoming.items():
        settings_key = _KEY_TO_META[json_key][0]
        old_value = getattr(settings, settings_key)
        history_entries.append(
            json.dumps(
                {
                    "changed_at": now_iso,
                    "field": json_key,
                    "old_value": str(old_value),
                    "new_value": str(new_value),
                    "changed_by": admin,
                }
            )
        )

    # Write to override file and update settings in memory
    # Convert json_keys to UPPER_CASE settings keys
    override_dict = {_KEY_TO_META[k][0]: v for k, v in incoming.items()}
    save_settings_override(override_dict)

    # Persist history in Redis (newest first, cap at 100)
    history_key = CacheKey.admin_settings_history()
    for entry in history_entries:
        await redis_client.lpush(history_key, entry)
    await redis_client.ltrim(history_key, 0, 99)

    # Invalidate dashboard cache since settings affect display
    await redis_client.delete(CacheKey.admin_dashboard_stats())

    return _build_response()


@router.get("/history")
async def get_settings_history(
    _admin: str = Depends(get_current_admin),
) -> list[dict]:
    raw = await redis_client.lrange(CacheKey.admin_settings_history(), 0, 19)
    return [json.loads(entry) for entry in raw]
