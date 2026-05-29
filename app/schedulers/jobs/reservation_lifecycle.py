from app.cache.client import redis_client
from app.cache.keys import CacheKey
from app.core.logging import get_logger
from app.db.session import AsyncSessionFactory
from app.services.reservation import ReservationService

logger = get_logger(__name__)

LOCK_TTL = 120  # 2 minutes — prevents double-run during overlapping scheduler ticks


async def complete_past_reservations_job() -> None:
    """APScheduler job: mark past active reservations as COMPLETED.

    Runs every 30 minutes. Uses a Redis lock to prevent concurrent runs.
    """
    lock_key = CacheKey.reservation_lifecycle_lock()
    acquired = await redis_client.set_nx(lock_key, "1", ttl=LOCK_TTL)
    if not acquired:
        logger.debug("reservation_lifecycle_skipped", reason="lock_held")
        return

    try:
        async with AsyncSessionFactory() as session:
            svc = ReservationService(session, redis_client)
            count = await svc.complete_past_reservations()
            await session.commit()
            logger.info("reservation_lifecycle_complete", completed=count)
    except Exception as exc:
        logger.error("reservation_lifecycle_failed", error=str(exc))
        raise
    finally:
        await redis_client.delete(lock_key)
