"""Metadata registry for admin-editable runtime settings.

Single source of truth: `app/api/admin/settings.py` builds GET/PATCH/metadata
responses purely by looping `SETTINGS_REGISTRY` below. Adding a new runtime
setting is exactly one new `SettingMeta` entry here — it then automatically
appears in the API response, the /metadata endpoint (so the admin-panel
tooltip/badge/validation all pick it up), and PATCH validation. No other file
needs to change.
"""

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

from app.core.config import (
    DEFAULT_RESERVATION_STRATEGY,
    RESERVATION_STRATEGIES,
    SELECTABLE_RESERVATION_STRATEGIES,
)


class RestartBehavior(str, Enum):
    LIVE = "live"
    CACHE_REFRESH = "cache_refresh"
    SCHEDULER_RESTART = "scheduler_restart"
    RESTART_REQUIRED = "restart_required"


CATEGORIES: list[tuple[str, str]] = [
    ("reservation_rules", "Reservations"),
    ("slot_schedule", "Slot Schedule"),
    ("rate_limits", "Rate Limits"),
    ("reminders", "Reminders"),
    ("score_notifications", "Score Notifications"),
    ("inactivity_reminder", "Inactivity Reminder"),
    ("broadcast", "Daily Broadcast"),
    ("user_broadcast", "User Broadcast"),
    ("membership", "Membership"),
    ("security", "Security"),
]
CATEGORY_LABELS: dict[str, str] = dict(CATEGORIES)


@dataclass(frozen=True)
class SettingMeta:
    key: str  # attribute name on Settings
    json_key: str  # snake_case key used in the API payload
    category: str  # slug — must be one of CATEGORIES
    label: str
    description: str
    value_type: type  # bool | int | float | str
    example: Any
    validator: str  # name dispatched in validate_and_coerce()
    min: float | int | None = None
    max: float | int | None = None
    placeholder: str | None = None
    restart_behavior: RestartBehavior = RestartBehavior.LIVE
    runtime_safe: bool = True
    # Optional UI-widget hint for the admin panel. "time" renders a native
    # HH:MM time picker; "select" renders a dropdown over `choices`; None falls
    # back to the default input for value_type.
    widget: str | None = None
    # (value, label) pairs for the "enum_choice" validator. Required by it and
    # surfaced in /metadata so the panel's dropdown and the backend validator
    # can never disagree about what is accepted. Tuple (not list) to keep the
    # frozen dataclass hashable.
    choices: tuple[tuple[str, str], ...] | None = None


# Human-readable label per reservation strategy. Indexed by RESERVATION_STRATEGIES
# rather than hand-listed so adding a strategy without a label fails loudly at
# import instead of shipping a dropdown that silently omits it.
_RESERVATION_STRATEGY_LABELS: dict[str, str] = {
    "THRESHOLD_UNLOCK": "Threshold unlock — channels open one by one as they fill",
    "SEQUENTIAL_FILL": "Sequential fill — one slot per time, channel picked automatically",
}

# Labelling every known strategy asserts each one has a label, including those
# not yet selectable — so enabling one later can never ship a blank dropdown
# entry. Only the selectable subset is then actually offered to the admin.
_ALL_STRATEGY_LABELS: tuple[tuple[str, str], ...] = tuple(
    (value, _RESERVATION_STRATEGY_LABELS[value]) for value in RESERVATION_STRATEGIES
)
_STRATEGY_CHOICES: tuple[tuple[str, str], ...] = tuple(
    (value, label)
    for value, label in _ALL_STRATEGY_LABELS
    if value in SELECTABLE_RESERVATION_STRATEGIES
)


SETTINGS_REGISTRY: list[SettingMeta] = [
    # ── Reservations ──────────────────────────────────────────────────────
    SettingMeta(
        key="MAX_ACTIVE_RESERVATIONS", json_key="max_active_reservations",
        category="reservation_rules", label="Max active reservations",
        description="Per-user cap on concurrently active (non-cancelled, non-completed) reservations.",
        value_type=int, example=10, validator="int_range", min=1, max=50,
    ),
    SettingMeta(
        key="MAX_RESERVATION_DAYS_AHEAD", json_key="max_reservation_days_ahead",
        category="reservation_rules", label="Max days ahead",
        description="How far in advance a user may book a slot.",
        value_type=int, example=14, validator="int_range", min=1, max=60,
    ),
    SettingMeta(
        key="RESERVATION_STRATEGY", json_key="reservation_strategy",
        category="reservation_rules", label="Reservation strategy",
        description=(
            "How slots are offered and which channel a booking lands on. "
            "Threshold unlock: users pick a slot from a specific channel, and each "
            "next channel opens once the previous one reaches the capacity threshold "
            "below. Sequential fill: users see each time once and never choose a "
            "channel — the booking goes to the highest-priority channel still free at "
            "that time, so channels fill in order and the threshold below is ignored. "
            "Only affects new bookings; existing reservations keep the channel they "
            "were made on."
        ),
        value_type=str, example=DEFAULT_RESERVATION_STRATEGY, validator="enum_choice",
        widget="select", choices=_STRATEGY_CHOICES,
    ),
    SettingMeta(
        key="CHANNEL_CAPACITY_THRESHOLD", json_key="channel_capacity_threshold",
        category="reservation_rules", label="Channel capacity threshold",
        description=(
            "Fraction of a channel's daily capacity at which the next channel becomes "
            "bookable. Only used by the Threshold unlock strategy — ignored under "
            "Sequential fill."
        ),
        value_type=float, example=0.70, validator="float_range", min=0.1, max=1.0,
        placeholder="0.70",
    ),
    SettingMeta(
        key="SAME_DAY_CUTOFF_HOUR", json_key="same_day_cutoff_hour",
        category="reservation_rules", label="Same-day cutoff time",
        description="Time (HH:MM, local timezone) after which same-day bookings are blocked.",
        value_type=str, example="12:00", validator="hh_mm_time", widget="time",
    ),
    SettingMeta(
        key="SAME_DAY_CANCEL_CUTOFF_HOUR", json_key="same_day_cancel_cutoff_hour",
        category="reservation_rules", label="Same-day cancel cutoff time",
        description="Time (HH:MM, local timezone) after which same-day cancellations are blocked.",
        value_type=str, example="12:00", validator="hh_mm_time", widget="time",
    ),
    # ── Slot Schedule ─────────────────────────────────────────────────────
    SettingMeta(
        key="SLOT_START_HOUR", json_key="slot_start_hour",
        category="slot_schedule", label="Slot start hour",
        description="First hour (0-23) slots are generated within. Applies to the next slot-generation run only — existing slots are unaffected.",
        value_type=int, example=16, validator="int_range", min=0, max=23,
    ),
    SettingMeta(
        key="SLOT_END_HOUR", json_key="slot_end_hour",
        category="slot_schedule", label="Slot end hour",
        description="Last hour (0-24, where 24 = midnight) slots are generated within. Applies to the next slot-generation run only.",
        value_type=int, example=24, validator="int_range", min=0, max=24,
    ),
    SettingMeta(
        key="SLOT_DURATION_MINUTES", json_key="slot_duration_minutes",
        category="slot_schedule", label="Slot duration (minutes)",
        description="Length of each generated slot. Applies to the next slot-generation run only.",
        value_type=int, example=30, validator="int_range", min=5, max=120,
    ),
    SettingMeta(
        key="ENABLE_FINAL_MIDNIGHT_SLOT", json_key="enable_final_midnight_slot",
        category="slot_schedule", label="Enable final midnight slot",
        description="Append one extra slot at a fixed time, on the same calendar day.",
        value_type=bool, example=True, validator="bool",
    ),
    SettingMeta(
        key="FINAL_SLOT_TIME", json_key="final_slot_time",
        category="slot_schedule", label="Final slot time (HH:MM)",
        description="Time of the extra terminal slot. Only used when the final midnight slot is enabled.",
        value_type=str, example="23:59", validator="hh_mm_time", placeholder="23:59",
        widget="time",
    ),
    # ── Rate Limits ───────────────────────────────────────────────────────
    SettingMeta(
        key="RATE_LIMIT_REQUESTS", json_key="rate_limit_requests",
        category="rate_limits", label="Rate limit requests",
        description="Max Telegram updates a single user may send within the rate-limit window.",
        value_type=int, example=30, validator="positive_int", min=1, max=1000,
    ),
    SettingMeta(
        key="RATE_LIMIT_WINDOW_SECONDS", json_key="rate_limit_window_seconds",
        category="rate_limits", label="Rate limit window (seconds)",
        description="Sliding window length the request cap above is measured over.",
        value_type=int, example=60, validator="positive_int", min=1, max=3600,
    ),
    SettingMeta(
        key="ANTI_FLOOD_SECONDS", json_key="anti_flood_seconds",
        category="rate_limits", label="Anti-flood interval (seconds)",
        description="Minimum time between consecutive actions from the same user.",
        value_type=float, example=0.5, validator="float_range", min=0.0, max=10.0,
    ),
    # ── Reminders ─────────────────────────────────────────────────────────
    SettingMeta(
        key="SAME_DAY_REMINDER_HOUR", json_key="same_day_reminder_hour",
        category="reminders", label="Same-day reminder time",
        description="Time (HH:MM, local timezone) the \"today's session\" reminder job fires.",
        value_type=str, example="12:00", validator="hh_mm_time", widget="time",
        restart_behavior=RestartBehavior.LIVE,
    ),
    SettingMeta(
        key="PRE_SESSION_REMINDER_MINUTES", json_key="pre_session_reminder_minutes",
        category="reminders", label="Pre-session reminder (minutes)",
        description="Minutes before session start the reminder is sent. Read live on every poll.",
        value_type=int, example=30, validator="int_range", min=5, max=180,
    ),
    SettingMeta(
        key="FINAL_REMINDER_ENABLED", json_key="final_reminder_enabled",
        category="reminders", label="Enable final live reminder",
        description="Master switch: send a final \"join now\" reminder minutes before the session starts.",
        value_type=bool, example=True, validator="bool",
    ),
    SettingMeta(
        key="FINAL_REMINDER_MINUTES", json_key="final_reminder_minutes",
        category="reminders", label="Final reminder (minutes)",
        description="Minutes before session start the final reminder fires. Forward-only window [now, now+N). Read live on every poll.",
        value_type=int, example=5, validator="int_range", min=1, max=60,
    ),
    # ── Score Notifications ──────────────────────────────────────────────
    SettingMeta(
        key="SCORE_CHANGE_NOTIFICATIONS_ENABLED", json_key="score_change_notifications_enabled",
        category="score_notifications", label="Enable score-change notifications",
        description="Master switch: DM the user whenever their participation score changes.",
        value_type=bool, example=True, validator="bool",
    ),
    SettingMeta(
        key="NOTIFY_ON_REWARD", json_key="notify_on_reward",
        category="score_notifications", label="Notify on reward",
        description="Send a DM when a reservation reward (+1) is applied. Opt-in — high churn.",
        value_type=bool, example=False, validator="bool",
    ),
    SettingMeta(
        key="NOTIFY_ON_CANCEL_ROLLBACK", json_key="notify_on_cancel_rollback",
        category="score_notifications", label="Notify on cancel rollback",
        description="Send a DM when a cancellation rollback (-1) is applied. Opt-in — high churn.",
        value_type=bool, example=False, validator="bool",
    ),
    SettingMeta(
        key="SCORE_NOTIFY_DELAY_SECONDS", json_key="score_notify_delay_seconds",
        category="score_notifications", label="Notify delay (seconds)",
        description="Delay before the delivery job runs, so the score-change transaction is guaranteed committed first.",
        value_type=int, example=5, validator="positive_int", min=1, max=300,
    ),
    # ── Inactivity Reminder ───────────────────────────────────────────────
    SettingMeta(
        key="INACTIVITY_REMINDER_ENABLED", json_key="inactivity_reminder_enabled",
        category="inactivity_reminder", label="Enable inactivity reminders",
        description="Master switch: DM users whose last reservation predates the threshold below.",
        value_type=bool, example=True, validator="bool",
    ),
    SettingMeta(
        key="INACTIVITY_REMINDER_THRESHOLD_DAYS", json_key="inactivity_reminder_threshold_days",
        category="inactivity_reminder", label="Inactivity threshold (days)",
        description="Days without a new reservation after which a reminder is due. Repeats every this many days.",
        value_type=int, example=30, validator="positive_int", min=1, max=365,
    ),
    SettingMeta(
        key="INACTIVITY_REMINDER_HOUR", json_key="inactivity_reminder_hour",
        category="inactivity_reminder", label="Daily scan time",
        description="Time (HH:MM, local timezone) the daily inactivity scan runs.",
        value_type=str, example="18:00", validator="hh_mm_time", widget="time",
        restart_behavior=RestartBehavior.LIVE,
    ),
    # ── Daily Broadcast ───────────────────────────────────────────────────
    SettingMeta(
        key="DAILY_BROADCAST_HOUR", json_key="daily_broadcast_hour",
        category="broadcast", label="Broadcast time",
        description="Time (HH:MM, local timezone) the daily schedule is posted to each channel.",
        value_type=str, example="12:00", validator="hh_mm_time", widget="time",
        restart_behavior=RestartBehavior.LIVE,
    ),
    SettingMeta(
        key="ENABLE_BROADCAST_AUTO_PIN", json_key="enable_broadcast_auto_pin",
        category="broadcast", label="Auto-pin broadcast message",
        description="Pin the broadcast message in the channel after sending.",
        value_type=bool, example=True, validator="bool",
    ),
    SettingMeta(
        key="DELETE_PREVIOUS_BROADCAST", json_key="delete_previous_broadcast",
        category="broadcast", label="Delete previous broadcast",
        description="Remove yesterday's broadcast message when publishing today's.",
        value_type=bool, example=False, validator="bool",
    ),
    # ── User Broadcast ────────────────────────────────────────────────────
    SettingMeta(
        key="USER_BROADCAST_RATE_LIMIT", json_key="user_broadcast_rate_limit",
        category="user_broadcast", label="User broadcast rate limit (msg/s)",
        description="Max direct messages per second when broadcasting to users. Telegram's global limit is ~30/s.",
        value_type=int, example=20, validator="positive_int", min=1, max=30,
    ),
    SettingMeta(
        key="MEDIA_STORAGE_CHAT_ID", json_key="media_storage_chat_id",
        category="user_broadcast", label="Media storage chat ID",
        description="Chat the bot uploads media to in order to obtain a reusable file_id. Leave blank to fall back to the first admin ID.",
        value_type=int, example=-1001234567890, validator="telegram_channel_id_optional",
        placeholder="-1001234567890",
    ),
    # ── Membership ────────────────────────────────────────────────────────
    SettingMeta(
        key="MEMBERSHIP_CACHE_TTL", json_key="membership_cache_ttl",
        category="membership", label="Membership cache TTL (seconds)",
        description="How long a successful membership check is cached. Applies to the next check, not retroactively. Recommended: 900-3600.",
        value_type=int, example=1800, validator="positive_int", min=60, max=86400,
        restart_behavior=RestartBehavior.CACHE_REFRESH,
    ),
    # ── Security ──────────────────────────────────────────────────────────
    SettingMeta(
        key="ADMIN_JWT_EXPIRE_MINUTES", json_key="admin_jwt_expire_minutes",
        category="security", label="Admin session lifetime (minutes)",
        description="How long a newly issued admin JWT is valid. Only affects tokens issued after the change — existing sessions are unaffected.",
        value_type=int, example=30, validator="positive_int", min=5, max=1440,
    ),
]

BY_JSON_KEY: dict[str, SettingMeta] = {m.json_key: m for m in SETTINGS_REGISTRY}
BY_SETTINGS_KEY: dict[str, SettingMeta] = {m.key: m for m in SETTINGS_REGISTRY}

_HH_MM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_TELEGRAM_CHANNEL_URL_RE = re.compile(r"^https://t\.me/.+")


def _validate_bool(meta: SettingMeta, raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str) and raw.lower() in ("true", "false"):
        return raw.lower() == "true"
    raise ValueError(f"{meta.json_key}: expected a boolean")


def _validate_int_range(meta: SettingMeta, raw: Any) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{meta.json_key}: expected an integer")
    if meta.min is not None and value < meta.min:
        raise ValueError(f"{meta.json_key}: minimum value is {meta.min}")
    if meta.max is not None and value > meta.max:
        raise ValueError(f"{meta.json_key}: maximum value is {meta.max}")
    return value


def _validate_float_range(meta: SettingMeta, raw: Any) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{meta.json_key}: expected a number")
    if meta.min is not None and value < meta.min:
        raise ValueError(f"{meta.json_key}: minimum value is {meta.min}")
    if meta.max is not None and value > meta.max:
        raise ValueError(f"{meta.json_key}: maximum value is {meta.max}")
    return value


def _validate_positive_int(meta: SettingMeta, raw: Any) -> int:
    return _validate_int_range(meta, raw)


def _validate_cron_hour(meta: SettingMeta, raw: Any) -> int:
    return _validate_int_range(meta, raw)


def _validate_hh_mm_time(meta: SettingMeta, raw: Any) -> str:
    value = str(raw)
    if not _HH_MM_RE.match(value):
        raise ValueError(f"{meta.json_key}: expected a 24-hour HH:MM time, e.g. 23:59")
    return value


def _validate_enum_choice(meta: SettingMeta, raw: Any) -> str:
    """Accept only one of meta.choices, case-insensitively, returning the
    canonical value. Matching is on the choice *value*, never the label."""
    if not meta.choices:
        raise ValueError(f"{meta.json_key}: no choices configured")
    text = str(raw).strip().upper()
    for value, _label in meta.choices:
        if value.upper() == text:
            return value
    allowed = ", ".join(value for value, _ in meta.choices)
    raise ValueError(f"{meta.json_key}: expected one of {allowed}")


def _validate_telegram_channel_id_optional(meta: SettingMeta, raw: Any) -> int | None:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{meta.json_key}: expected a Telegram channel ID (negative integer)")
    if value >= 0:
        raise ValueError(f"{meta.json_key}: Telegram channel/supergroup IDs are negative integers")
    return value


_VALIDATORS: dict[str, Callable[[SettingMeta, Any], Any]] = {
    "bool": _validate_bool,
    "int_range": _validate_int_range,
    "float_range": _validate_float_range,
    "positive_int": _validate_positive_int,
    "cron_hour": _validate_cron_hour,
    "hh_mm_time": _validate_hh_mm_time,
    "enum_choice": _validate_enum_choice,
    "telegram_channel_id_optional": _validate_telegram_channel_id_optional,
}


def validate_and_coerce(meta: SettingMeta, raw: Any) -> Any:
    """Coerce + validate a raw PATCH value per its registry entry. Raises ValueError."""
    return _VALIDATORS[meta.validator](meta, raw)


def validate_membership_channel_id(raw: Any) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValueError("channel id: expected a Telegram channel ID (negative integer)")
    if value >= 0:
        raise ValueError("channel id: Telegram channel/supergroup IDs are negative integers")
    return value


def validate_membership_channel_url(raw: Any) -> str:
    value = str(raw)
    if not _TELEGRAM_CHANNEL_URL_RE.match(value):
        raise ValueError("channel url: expected a URL starting with https://t.me/")
    return value
