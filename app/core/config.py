import json
import os
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Persisted via a host bind mount (see docker-compose.yml `app` service's
# `./data:/app/data` volume) rather than a database table — a single JSON file
# is enough for one admin-editable settings blob and avoids adding a DB
# dependency the spec calls "unnecessary infrastructure" for this use case.
SETTINGS_OVERRIDE_PATH = Path("data/admin_settings_override.json")

# Highest supported REQUIRED_CHANNEL_N_* suffix.
MAX_REQUIRED_CHANNELS = 5


@dataclass(frozen=True)
class ChannelConfig:
    """A mandatory-membership channel: ID for verification, URL for UI buttons."""

    id: int
    url: str


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ── Bot ───────────────────────────────────────────────────────────────
    BOT_TOKEN: str
    WEBHOOK_URL: Optional[str] = None
    WEBHOOK_PATH: str = "/webhook"
    WEBHOOK_SECRET: Optional[str] = None

    # ── Application ───────────────────────────────────────────────────────
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    DEBUG: bool = False
    ENVIRONMENT: str = "production"

    # ── Database ──────────────────────────────────────────────────────────
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "reservations"
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str

    # ── Redis ─────────────────────────────────────────────────────────────
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: Optional[str] = None

    # ── Timezone ──────────────────────────────────────────────────────────
    TIMEZONE: str = "Asia/Baghdad"

    # ── Reservation rules ─────────────────────────────────────────────────
    MAX_ACTIVE_RESERVATIONS: int = 10
    MAX_RESERVATION_DAYS_AHEAD: int = 14
    CHANNEL_CAPACITY_THRESHOLD: float = 0.70
    # Hour (0-23, local timezone) after which same-day reservations are blocked
    SAME_DAY_CUTOFF_HOUR: int = 12
    # Hour (0-23, local timezone) after which same-day cancellations are blocked
    SAME_DAY_CANCEL_CUTOFF_HOUR: int = 12

    # ── Slot schedule ─────────────────────────────────────────────────────
    SLOT_START_HOUR: int = 16   # 4:00 PM
    SLOT_END_HOUR: int = 24     # 12:00 AM (midnight)
    SLOT_DURATION_MINUTES: int = 30
    # Append one special terminal slot at the given time (HH:MM, 24-hour).
    # Keeps the slot on the same calendar day — avoids midnight rollover.
    ENABLE_FINAL_MIDNIGHT_SLOT: bool = True
    FINAL_SLOT_TIME: str = "23:59"

    # ── Rate limiting ─────────────────────────────────────────────────────
    RATE_LIMIT_REQUESTS: int = 30
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    ANTI_FLOOD_SECONDS: float = 0.5

    # ── Notifications & Reminders ─────────────────────────────────────────
    # Hour (0-23, local timezone) same-day reminders are dispatched
    SAME_DAY_REMINDER_HOUR: int = 12
    # Minutes before session start to send the pre-session reminder
    PRE_SESSION_REMINDER_MINUTES: int = 30

    # ── Score-change notifications ────────────────────────────────────────
    # Master switch: DM the user whenever their participation score changes.
    SCORE_CHANGE_NOTIFICATIONS_ENABLED: bool = True
    # Reservation reward (+1) and cancellation rollback (-1) are high-churn and
    # often not worth notifying — opt in explicitly.
    NOTIFY_ON_REWARD: bool = False
    NOTIFY_ON_CANCEL_ROLLBACK: bool = False
    # Delay (seconds) before the one-off delivery job runs. Must be > 0 so the
    # enclosing DB transaction is guaranteed committed before the job reads the
    # row (delivery happens out-of-band, never inside the score transaction).
    SCORE_NOTIFY_DELAY_SECONDS: int = 5

    # ── Inactivity Reminder ────────────────────────────────────────────────
    # Master switch: DM users whose last reservation predates the threshold.
    INACTIVITY_REMINDER_ENABLED: bool = True
    # Days without a new reservation after which a reminder is due. Repeats
    # every this many days until the user reserves again.
    INACTIVITY_REMINDER_THRESHOLD_DAYS: int = 30
    # Hour (0-23, local timezone) the daily inactivity scan runs.
    INACTIVITY_REMINDER_HOUR: int = 18

    # ── Daily Broadcast ───────────────────────────────────────────────────
    # Hour (0-23, local timezone) daily schedule is broadcast to each channel
    DAILY_BROADCAST_HOUR: int = 12
    # Pin the broadcast message in the channel after sending
    ENABLE_BROADCAST_AUTO_PIN: bool = True
    # Delete the previous day's broadcast when publishing today's
    DELETE_PREVIOUS_BROADCAST: bool = False

    # ── User Broadcast ────────────────────────────────────────────────────
    # Max direct messages per second when broadcasting to users (Telegram's
    # global limit is ~30/s; stay below it to avoid 429 flood-control).
    USER_BROADCAST_RATE_LIMIT: int = 20
    # Chat the bot uploads media to in order to obtain a reusable Telegram
    # file_id (no binaries are stored). Falls back to the first ADMIN_IDS entry.
    MEDIA_STORAGE_CHAT_ID: Optional[int] = None

    # ── Logging ───────────────────────────────────────────────────────────
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"

    # ── Mandatory Channel Membership ──────────────────────────────────────
    # Each required channel is an ID + URL pair. The ID (negative integer) is
    # used only for Telegram membership verification; the URL is used only for
    # the "Join" UI buttons. Empty entries are ignored. If no valid channel IDs
    # are configured, membership verification is disabled entirely.
    REQUIRED_CHANNEL_1_ID: Optional[int] = None
    REQUIRED_CHANNEL_1_URL: Optional[str] = None
    REQUIRED_CHANNEL_2_ID: Optional[int] = None
    REQUIRED_CHANNEL_2_URL: Optional[str] = None
    REQUIRED_CHANNEL_3_ID: Optional[int] = None
    REQUIRED_CHANNEL_3_URL: Optional[str] = None
    REQUIRED_CHANNEL_4_ID: Optional[int] = None
    REQUIRED_CHANNEL_4_URL: Optional[str] = None
    REQUIRED_CHANNEL_5_ID: Optional[int] = None
    REQUIRED_CHANNEL_5_URL: Optional[str] = None
    # How long (seconds) a successful membership check is cached in Redis.
    MEMBERSHIP_CACHE_TTL: int = 1800

    # ── Admin (Telegram) ──────────────────────────────────────────────────
    ADMIN_IDS: str = ""  # comma-separated telegram IDs

    # ── Admin Panel ───────────────────────────────────────────────────────
    ADMIN_USERNAME: str = "admin"
    # Store the bcrypt hash of the password here (use: python -c "from passlib.hash import bcrypt; print(bcrypt.hash('yourpassword'))")
    ADMIN_PASSWORD: str = ""
    ADMIN_JWT_SECRET: str = ""
    ADMIN_JWT_EXPIRE_MINUTES: int = 30

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def database_url_sync(self) -> str:
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def redis_url(self) -> str:
        if self.REDIS_PASSWORD:
            return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    @property
    def admin_id_list(self) -> list[int]:
        if not self.ADMIN_IDS:
            return []
        return [int(x.strip()) for x in self.ADMIN_IDS.split(",") if x.strip()]

    @property
    def required_channels(self) -> list[ChannelConfig]:
        """Configured mandatory-membership channels (entries without an ID are ignored)."""
        channels: list[ChannelConfig] = []
        for i in range(1, MAX_REQUIRED_CHANNELS + 1):
            channel_id = getattr(self, f"REQUIRED_CHANNEL_{i}_ID")
            if channel_id is None:
                continue
            url = getattr(self, f"REQUIRED_CHANNEL_{i}_URL") or ""
            channels.append(ChannelConfig(id=int(channel_id), url=url))
        return channels

    @field_validator(
        *[f"REQUIRED_CHANNEL_{i}_ID" for i in range(1, MAX_REQUIRED_CHANNELS + 1)],
        *[f"REQUIRED_CHANNEL_{i}_URL" for i in range(1, MAX_REQUIRED_CHANNELS + 1)],
        "MEDIA_STORAGE_CHAT_ID",
        mode="before",
    )
    @classmethod
    def _blank_channel_to_none(cls, v: object) -> object:
        """Treat empty/whitespace env values as unset so blank entries are ignored."""
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator("CHANNEL_CAPACITY_THRESHOLD")
    @classmethod
    def validate_threshold(cls, v: float) -> float:
        if not 0 < v < 1:
            raise ValueError("CHANNEL_CAPACITY_THRESHOLD must be between 0 and 1")
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()


def load_settings_override() -> None:
    """Apply admin_settings_override.json on top of env-var settings at startup."""
    if not SETTINGS_OVERRIDE_PATH.exists():
        return
    try:
        data = json.loads(SETTINGS_OVERRIDE_PATH.read_text(encoding="utf-8"))
        for key, value in data.items():
            if hasattr(settings, key):
                object.__setattr__(settings, key, value)
    except Exception:
        pass  # malformed file must never break startup


def save_settings_override(updates: dict) -> None:
    """Merge updates into the override file and apply to the live settings object.

    Callers (the admin settings router) are responsible for serializing
    concurrent calls — this function itself does a plain read-modify-write.
    """
    SETTINGS_OVERRIDE_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing: dict = {}
    if SETTINGS_OVERRIDE_PATH.exists():
        try:
            existing = json.loads(SETTINGS_OVERRIDE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    existing.update(updates)

    # Write atomically: a crash mid-write must never leave a truncated/corrupt
    # override file, since load_settings_override() would then silently fall
    # back to defaults on next startup.
    fd, tmp_path = tempfile.mkstemp(
        dir=SETTINGS_OVERRIDE_PATH.parent, prefix=".tmp-", suffix=".json"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(existing, indent=2, ensure_ascii=False))
        os.replace(tmp_path, SETTINGS_OVERRIDE_PATH)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    for key, value in updates.items():
        if hasattr(settings, key):
            object.__setattr__(settings, key, value)
