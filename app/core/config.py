from functools import lru_cache
from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # ── Rate limiting ─────────────────────────────────────────────────────
    RATE_LIMIT_REQUESTS: int = 30
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    ANTI_FLOOD_SECONDS: float = 0.5

    # ── Logging ───────────────────────────────────────────────────────────
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"

    # ── Admin ─────────────────────────────────────────────────────────────
    ADMIN_IDS: str = ""  # comma-separated telegram IDs

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
