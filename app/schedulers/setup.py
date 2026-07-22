from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.core.logging import get_logger
from app.schedulers.jobs.broadcast import send_daily_schedule_job
from app.schedulers.jobs.inactivity_reminder import send_inactivity_reminders_job
from app.schedulers.jobs.recurring_broadcast import dispatch_recurring_broadcasts_job
from app.schedulers.jobs.reminders import (
    send_final_reminders_job,
    send_pre_session_reminders_job,
    send_same_day_reminders_job,
)
from app.schedulers.jobs.reservation_lifecycle import complete_past_reservations_job
from app.schedulers.jobs.slot_generation import generate_upcoming_slots

logger = get_logger(__name__)

# Module-level handle so background jobs (e.g. the recurring dispatcher) can
# enqueue one-off delivery jobs without an app/request reference.
_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler | None:
    return _scheduler


def create_scheduler() -> AsyncIOScheduler:
    global _scheduler
    scheduler = AsyncIOScheduler(timezone=settings.TIMEZONE)

    # Run at midnight and 6 AM every day to ensure next-14-day slots exist
    scheduler.add_job(
        generate_upcoming_slots,
        trigger=CronTrigger(hour="0,6", minute=0, timezone=settings.TIMEZONE),
        id="slot_generation",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    # Run every 30 minutes to transition past active reservations → completed
    scheduler.add_job(
        complete_past_reservations_job,
        trigger=CronTrigger(minute="0,30", timezone=settings.TIMEZONE),
        id="reservation_lifecycle",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    # Run at the configured reminder hour — reminds users of today's sessions
    scheduler.add_job(
        send_same_day_reminders_job,
        trigger=CronTrigger(hour=settings.SAME_DAY_REMINDER_HOUR, minute=0, timezone=settings.TIMEZONE),
        id="same_day_reminders",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    # Run every 5 minutes — catches sessions starting in ~30 minutes
    scheduler.add_job(
        send_pre_session_reminders_job,
        trigger=CronTrigger(minute="*/5", timezone=settings.TIMEZONE),
        id="pre_session_reminders",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    # Run every minute — final "join now" reminder just before session start
    scheduler.add_job(
        send_final_reminders_job,
        trigger=CronTrigger(minute="*", timezone=settings.TIMEZONE),
        id="final_reminders",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    # Run at the configured broadcast hour — publishes today's schedule to each channel
    scheduler.add_job(
        send_daily_schedule_job,
        trigger=CronTrigger(hour=settings.DAILY_BROADCAST_HOUR, minute=0, timezone=settings.TIMEZONE),
        id="daily_broadcast",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    # Run every minute — fire due recurring broadcast rules
    scheduler.add_job(
        dispatch_recurring_broadcasts_job,
        trigger=CronTrigger(minute="*", timezone=settings.TIMEZONE),
        id="recurring_broadcast_dispatch",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    # Run at the configured hour — DM users overdue for a reservation reminder
    scheduler.add_job(
        send_inactivity_reminders_job,
        trigger=CronTrigger(hour=settings.INACTIVITY_REMINDER_HOUR, minute=0, timezone=settings.TIMEZONE),
        id="inactivity_reminders",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    _scheduler = scheduler
    logger.info("scheduler_configured")
    return scheduler
