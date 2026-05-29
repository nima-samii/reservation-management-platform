from app.cache.client import redis_client
from app.cache.keys import CacheKey
from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import AsyncSessionFactory
from app.services.slot import SlotService

logger = get_logger(__name__)

LOCK_TTL = 300  # 5 minutes — prevents double-run across restarts


async def generate_upcoming_slots(force: bool = False) -> None:
    """
    APScheduler job: generates slots for the next N days.
    Uses a Redis lock to prevent concurrent runs.

    Pass force=True on startup to clear any stale lock and always run.
    """
    lock_key = CacheKey.slot_generation_lock()

    if force:
        await redis_client.delete(lock_key)

    acquired = await redis_client.set_nx(lock_key, "1", ttl=LOCK_TTL)
    if not acquired:
        logger.debug("slot_generation_skipped", reason="lock_held")
        return

    try:
        async with AsyncSessionFactory() as session:
            svc = SlotService(session)
            results = await svc.generate_slots_for_next_n_days(
                settings.MAX_RESERVATION_DAYS_AHEAD
            )
            total = sum(results.values())
            await session.commit()
            logger.info("slot_generation_complete", total_created=total, per_day=results)
    except Exception as exc:
        logger.error("slot_generation_failed", error=str(exc))
        raise
    finally:
        await redis_client.delete(lock_key)
