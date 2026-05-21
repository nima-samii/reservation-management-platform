from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.core.logging import get_logger
from app.schedulers.jobs.reservation_lifecycle import complete_past_reservations_job
from app.schedulers.jobs.slot_generation import generate_upcoming_slots

logger = get_logger(__name__)


def create_scheduler() -> AsyncIOScheduler:
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

    logger.info("scheduler_configured")
    return scheduler
