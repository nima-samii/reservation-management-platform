import asyncio
import json
from datetime import datetime
from typing import Any

import pytz
from fastapi import APIRouter, Depends, HTTPException, status

from app.api.admin.deps import get_current_admin
from app.api.admin.schemas.settings import (
    MembershipChannelsBody,
    SettingCategoryMetaOut,
    SettingChoiceOut,
    SettingFieldMetaOut,
)
from app.cache.client import redis_client
from app.cache.keys import CacheKey
from app.core.config import MAX_REQUIRED_CHANNELS, save_settings_override, settings
from app.core.settings_registry import (
    BY_JSON_KEY,
    CATEGORIES,
    SETTINGS_REGISTRY,
    validate_and_coerce,
    validate_membership_channel_id,
    validate_membership_channel_url,
)
from app.schedulers.setup import apply_scheduler_setting_changes

router = APIRouter(tags=["admin-settings"])
TZ = pytz.timezone(settings.TIMEZONE)

_VALID_CATEGORIES = {slug for slug, _ in CATEGORIES}

# Serializes settings-override writes within THIS process only. The app runs a
# single uvicorn worker (see docker/Dockerfile CMD, no --workers flag) so this
# is sufficient today. If it ever runs multiple workers/replicas, this must
# become a cross-process file lock, or the override store must move to the
# database — otherwise the read-modify-write race in save_settings_override()
# comes back.
_override_lock = asyncio.Lock()


def _build_response() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {slug: {} for slug, _ in CATEGORIES}
    for meta in SETTINGS_REGISTRY:
        result[meta.category][meta.json_key] = getattr(settings, meta.key)
    return result


@router.get("/metadata")
async def get_settings_metadata(
    _admin: str = Depends(get_current_admin),
) -> list[SettingCategoryMetaOut]:
    by_category: dict[str, list[SettingFieldMetaOut]] = {slug: [] for slug, _ in CATEGORIES}
    for meta in SETTINGS_REGISTRY:
        by_category[meta.category].append(
            SettingFieldMetaOut(
                key=meta.json_key,
                label=meta.label,
                description=meta.description,
                type=meta.value_type.__name__,
                example=meta.example,
                min=meta.min,
                max=meta.max,
                placeholder=meta.placeholder,
                restart_behavior=meta.restart_behavior.value,
                runtime_safe=meta.runtime_safe,
                widget=meta.widget,
                choices=(
                    [
                        SettingChoiceOut(value=value, label=label)
                        for value, label in meta.choices
                    ]
                    if meta.choices
                    else None
                ),
            )
        )
    return [
        SettingCategoryMetaOut(key=slug, label=label, fields=by_category[slug])
        for slug, label in CATEGORIES
        if by_category[slug]
    ]


@router.get("")
async def get_settings_endpoint(
    _admin: str = Depends(get_current_admin),
) -> dict:
    return _build_response()


@router.patch("")
async def patch_settings(
    body: dict[str, dict[str, Any]],
    admin: str = Depends(get_current_admin),
) -> dict:
    incoming: dict[str, Any] = {}  # json_key -> coerced value
    for category_name, section in body.items():
        if category_name not in _VALID_CATEGORIES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unknown category: {category_name}",
            )
        for json_key, raw_value in (section or {}).items():
            meta = BY_JSON_KEY.get(json_key)
            if meta is None or meta.category != category_name:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Unknown setting: {json_key}",
                )
            try:
                incoming[json_key] = validate_and_coerce(meta, raw_value)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=str(exc),
                )

    if not incoming:
        return _build_response()

    # Cross-field check: a slot schedule with start >= end can never produce a slot.
    if "slot_start_hour" in incoming or "slot_end_hour" in incoming:
        start = incoming.get("slot_start_hour", settings.SLOT_START_HOUR)
        end = incoming.get("slot_end_hour", settings.SLOT_END_HOUR)
        if start >= end:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="slot_start_hour must be before slot_end_hour",
            )

    async with _override_lock:
        now_iso = datetime.now(TZ).isoformat()
        history_entries = []
        for json_key, new_value in incoming.items():
            meta = BY_JSON_KEY[json_key]
            old_value = getattr(settings, meta.key)
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

        override_dict = {BY_JSON_KEY[k].key: v for k, v in incoming.items()}
        save_settings_override(override_dict)

        # Hour-based scheduler jobs bake their cron trigger at startup; reschedule
        # any that just changed so the new hour applies without a process restart.
        apply_scheduler_setting_changes(override_dict.keys())

        history_key = CacheKey.admin_settings_history()
        for entry in history_entries:
            await redis_client.lpush(history_key, entry)
        await redis_client.ltrim(history_key, 0, 99)

    await redis_client.delete(CacheKey.admin_dashboard_stats())

    return _build_response()


@router.get("/history")
async def get_settings_history(
    _admin: str = Depends(get_current_admin),
) -> list[dict]:
    raw = await redis_client.lrange(CacheKey.admin_settings_history(), 0, 19)
    return [json.loads(entry) for entry in raw]


@router.get("/membership-channels")
async def get_membership_channels(
    _admin: str = Depends(get_current_admin),
) -> list[dict]:
    return [{"id": c.id, "url": c.url} for c in settings.required_channels]


@router.put("/membership-channels")
async def put_membership_channels(
    body: MembershipChannelsBody,
    admin: str = Depends(get_current_admin),
) -> list[dict]:
    if len(body.channels) > MAX_REQUIRED_CHANNELS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Maximum {MAX_REQUIRED_CHANNELS} membership channels supported",
        )

    validated: list[dict] = []
    for row in body.channels:
        try:
            channel_id = validate_membership_channel_id(row.id)
            url = validate_membership_channel_url(row.url)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            )
        validated.append({"id": channel_id, "url": url})

    old_channels = [{"id": c.id, "url": c.url} for c in settings.required_channels]

    async with _override_lock:
        override_dict: dict[str, Any] = {}
        for i in range(1, MAX_REQUIRED_CHANNELS + 1):
            if i <= len(validated):
                override_dict[f"REQUIRED_CHANNEL_{i}_ID"] = validated[i - 1]["id"]
                override_dict[f"REQUIRED_CHANNEL_{i}_URL"] = validated[i - 1]["url"]
            else:
                override_dict[f"REQUIRED_CHANNEL_{i}_ID"] = None
                override_dict[f"REQUIRED_CHANNEL_{i}_URL"] = None
        save_settings_override(override_dict)

        history_key = CacheKey.admin_settings_history()
        await redis_client.lpush(
            history_key,
            json.dumps(
                {
                    "changed_at": datetime.now(TZ).isoformat(),
                    "field": "required_channels",
                    "old_value": json.dumps(old_channels),
                    "new_value": json.dumps(validated),
                    "changed_by": admin,
                }
            ),
        )
        await redis_client.ltrim(history_key, 0, 99)

    return validated
