from app.bot.client import get_bot
from app.cache.client import redis_client
from app.cache.keys import CacheKey
from app.core.logging import get_logger
from app.db.session import AsyncSessionFactory
from app.services.broadcast import BroadcastService

logger = get_logger(__name__)

LOCK_TTL = 300  # 5 minutes — broadcast involves one Telegram call per channel


async def send_daily_schedule_job() -> None:
    """APScheduler job: publishes today's session schedule to each active channel.

    Runs once per day at 12:00 PM Baghdad time (same moment as same-day reminders).
    Redis lock prevents duplicate execution on multi-instance deployments.
    The bot must be an admin of each channel with 'Post messages' and 'Pin messages' permissions.
    """
    lock_key = CacheKey.daily_broadcast_lock()
    acquired = await redis_client.set_nx(lock_key, "1", ttl=LOCK_TTL)
    if not acquired:
        logger.debug("daily_broadcast_skipped", reason="lock_held")
        return

    try:
        bot = get_bot()
        async with AsyncSessionFactory() as session:
            svc = BroadcastService(session, bot)
            results = await svc.run_daily_broadcast()
            await session.commit()
        logger.info("daily_broadcast_complete", results=results)
    except Exception as exc:
        logger.error("daily_broadcast_job_failed", error=str(exc))
    finally:
        await redis_client.delete(lock_key)
