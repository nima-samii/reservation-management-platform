from app.bot.client import get_bot
from app.cache.client import redis_client
from app.cache.keys import CacheKey
from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import AsyncSessionFactory
from app.services.notification import ReminderService

logger = get_logger(__name__)

LOCK_TTL = 60  # seconds — both jobs are short-lived


async def send_same_day_reminders_job() -> None:
    """APScheduler job: sends 12 PM same-day reminders for today's sessions.
    Runs once per day at noon (Baghdad time). Redis lock prevents double-fire."""
    lock_key = CacheKey.same_day_reminder_lock()
    acquired = await redis_client.set_nx(lock_key, "1", ttl=LOCK_TTL)
    if not acquired:
        logger.debug("same_day_reminders_skipped", reason="lock_held")
        return

    try:
        bot = get_bot()
        async with AsyncSessionFactory() as session:
            svc = ReminderService(session, bot)
            count = await svc.send_same_day_reminders()
            await session.commit()
        logger.info("same_day_reminders_complete", sent=count)
    except Exception as exc:
        logger.error("same_day_reminders_job_failed", error=str(exc))
    finally:
        await redis_client.delete(lock_key)


async def send_pre_session_reminders_job() -> None:
    """APScheduler job: sends 30-minute-before reminders.
    Runs every 5 minutes; checks a ±5-minute window to tolerate jitter.
    The unique constraint on notification_logs prevents duplicate delivery."""
    lock_key = CacheKey.pre_session_reminder_lock()
    acquired = await redis_client.set_nx(lock_key, "1", ttl=LOCK_TTL)
    if not acquired:
        logger.debug("pre_session_reminders_skipped", reason="lock_held")
        return

    try:
        bot = get_bot()
        async with AsyncSessionFactory() as session:
            svc = ReminderService(session, bot)
            count = await svc.send_pre_session_reminders()
            await session.commit()
        if count:
            logger.info("pre_session_reminders_complete", sent=count)
    except Exception as exc:
        logger.error("pre_session_reminders_job_failed", error=str(exc))
    finally:
        await redis_client.delete(lock_key)


async def send_final_reminders_job() -> None:
    """APScheduler job: sends the final "join now" reminder just before start.
    Runs every minute; the forward-only window means a session is reminded on
    the first tick it comes within FINAL_REMINDER_MINUTES of starting.
    Gated by FINAL_REMINDER_ENABLED. Only SENT logs suppress redelivery, so a
    transient failure is retried on the next tick while still in-window."""
    if not settings.FINAL_REMINDER_ENABLED:
        return

    lock_key = CacheKey.final_reminder_lock()
    acquired = await redis_client.set_nx(lock_key, "1", ttl=LOCK_TTL)
    if not acquired:
        logger.debug("final_reminders_skipped", reason="lock_held")
        return

    try:
        bot = get_bot()
        async with AsyncSessionFactory() as session:
            svc = ReminderService(session, bot)
            count = await svc.send_final_reminders()
            await session.commit()
        if count:
            logger.info("final_reminders_complete", sent=count)
    except Exception as exc:
        logger.error("final_reminders_job_failed", error=str(exc))
    finally:
        await redis_client.delete(lock_key)
