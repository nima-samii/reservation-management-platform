"""Pure recurrence math for broadcast_recurring_rules.

Supports daily / weekly / monthly only (no yearly). Kept dependency-free and
side-effect-free so it is trivially unit-testable.
"""
import calendar
from datetime import datetime, timedelta

from app.db.models.user_broadcast import RecurrenceFrequency


def _add_months(dt: datetime, months: int) -> datetime:
    m = dt.month - 1 + months
    year = dt.year + m // 12
    month = m % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def _set_day(dt: datetime, day_of_month: int) -> datetime:
    day = min(day_of_month, calendar.monthrange(dt.year, dt.month)[1])
    return dt.replace(day=day)


def compute_next_run(
    *,
    frequency: str,
    interval: int,
    day_of_week: int | None,
    day_of_month: int | None,
    after: datetime,
    hour: int | None = None,
    minute: int | None = None,
) -> datetime:
    """Next fire time strictly after ``after``.

    Used both for the first run (after=now) and each subsequent run.

    Time-of-day handling:
    - When ``hour`` is None, the time-of-day is preserved from ``after`` (the
      original behavior: the recurrence is anchored to whenever the rule was
      created / last fired).
    - When ``hour`` is given, the result is pinned to ``hour:minute`` so the
      admin can choose a specific delivery time. For a daily rule whose chosen
      time is still ahead today, the first run lands today; otherwise it rolls
      forward by ``interval`` days.
    """
    interval = max(interval, 1)

    def at_time(dt: datetime) -> datetime:
        if hour is None:
            return dt
        return dt.replace(hour=hour, minute=minute or 0, second=0, microsecond=0)

    if frequency == RecurrenceFrequency.DAILY.value:
        candidate = at_time(after)
        if hour is not None and candidate > after:
            return candidate
        return at_time(after + timedelta(days=interval))

    if frequency == RecurrenceFrequency.WEEKLY.value:
        if day_of_week is None:
            return at_time(after + timedelta(weeks=interval))
        days_ahead = (day_of_week - after.weekday()) % 7
        candidate = at_time(after + timedelta(days=days_ahead))
        if candidate <= after:
            candidate = at_time(after + timedelta(days=days_ahead + 7))
        return candidate + timedelta(weeks=interval - 1)

    if frequency == RecurrenceFrequency.MONTHLY.value:
        if day_of_month is None:
            return at_time(_add_months(after, interval))
        candidate = at_time(_set_day(after, day_of_month))
        if candidate <= after:
            candidate = at_time(_set_day(_add_months(after, 1), day_of_month))
        if interval > 1:
            candidate = at_time(_set_day(_add_months(candidate, interval - 1), day_of_month))
        return candidate

    raise ValueError(f"unsupported frequency: {frequency}")
