from app.bot.client import get_bot
from app.cache.client import redis_client
from app.cache.keys import CacheKey
from app.core.logging import get_logger
from app.db.session import AsyncSessionFactory
from app.services.inactivity_reminder import InactivityReminderService

logger = get_logger(__name__)

# Generous TTL — unlike the short reminder jobs, this scan can page through
# the whole users table with a throttled send loop and legitimately run long.
LOCK_TTL = 3600


async def send_inactivity_reminders_job() -> None:
    """APScheduler job: daily scan for users overdue for a reservation
    reminder. Redis lock prevents double-fire across restarts/instances."""
    lock_key = CacheKey.inactivity_reminder_lock()
    acquired = await redis_client.set_nx(lock_key, "1", ttl=LOCK_TTL)
    if not acquired:
        logger.debug("inactivity_reminders_skipped", reason="lock_held")
        return

    try:
        bot = get_bot()
        async with AsyncSessionFactory() as session:
            svc = InactivityReminderService(session, bot)
            counts = await svc.send_due_reminders()
        logger.info("inactivity_reminders_complete", **counts)
    except Exception as exc:
        logger.error("inactivity_reminders_job_failed", error=str(exc))
    finally:
        await redis_client.delete(lock_key)
