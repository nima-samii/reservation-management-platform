"""
Pure, timezone-aware booking business rules.

All functions here are stateless and dependency-free so they can be
unit-tested without a database or running application.
"""
from datetime import date, datetime


def is_same_day_cutoff_passed(
    target_date: date,
    now: datetime,
    cutoff_hour: int,
) -> bool:
    """Return True when same-day reservations should be blocked.

    Blocks bookings for *target_date* when:
      - target_date is today (in *now*'s timezone), AND
      - current time is at or past cutoff_hour:00:00 local time.

    Both *now* and the derived cutoff must share the same tzinfo so that
    the comparison is always timezone-correct.

    Examples (cutoff_hour=12, Asia/Baghdad):
        11:59 AM today  → False  (still allowed)
        12:00 PM today  → True   (blocked)
         3:00 PM today  → True   (blocked)
         3:00 PM tomorrow → False (future day, never blocked by this rule)
    """
    if target_date != now.date():
        return False
    cutoff = now.replace(hour=cutoff_hour, minute=0, second=0, microsecond=0)
    return now >= cutoff


def can_cancel_reservation(
    slot_datetime: datetime,
    now: datetime,
    cancel_cutoff_hour: int,
) -> bool:
    """Return True if a reservation is still eligible for cancellation.

    Cancellation is blocked when either:
      - The slot has already passed (slot_datetime <= now), OR
      - The slot is today AND current time is at or past cancel_cutoff_hour.

    *slot_datetime* is converted to *now*'s timezone before date comparison
    so the check is always timezone-correct regardless of how the slot was stored.

    Examples (cancel_cutoff_hour=12, Asia/Baghdad):
        Slot: today 4:00 PM, now: 11:00 AM → True  (still cancellable)
        Slot: today 4:00 PM, now: 12:00 PM → False (cutoff passed)
        Slot: today 4:00 PM, now:  5:00 PM → False (slot has passed)
        Slot: tomorrow 4:00 PM, now: 3:00 PM → True  (future day, always cancellable)
    """
    if slot_datetime <= now:
        return False
    slot_local_date = slot_datetime.astimezone(now.tzinfo).date()
    return not is_same_day_cutoff_passed(slot_local_date, now, cancel_cutoff_hour)
