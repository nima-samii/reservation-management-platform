from datetime import datetime

import pytz

from app.core.config import settings

TZ = pytz.timezone(settings.TIMEZONE)


def now_tz() -> datetime:
    return datetime.now(TZ)


def format_slot_datetime(dt: datetime) -> str:
    local = dt.astimezone(TZ)
    return local.strftime("%A, %d %B %Y at %I:%M %p")


def format_date(dt: datetime) -> str:
    local = dt.astimezone(TZ)
    return local.strftime("%A, %d %B %Y")


def format_time(dt: datetime) -> str:
    local = dt.astimezone(TZ)
    return local.strftime("%I:%M %p")
