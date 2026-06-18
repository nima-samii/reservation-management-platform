import uuid

from app.bot.client import get_bot
from app.cache.client import redis_client
from app.cache.keys import CacheKey
from app.core.logging import get_logger
from app.db.session import AsyncSessionFactory
from app.services.user_broadcast import UserBroadcastService

logger = get_logger(__name__)

# Generous TTL: a large audience at the configured rate can take a long time
# (e.g. 50k recipients at 20/s ≈ 40 min). The lock only guards against the same
# broadcast id running twice concurrently.
LOCK_TTL = 7200  # 2 hours


async def run_user_broadcast_job(broadcast_id: str) -> None:
    """APScheduler one-off job: deliver a user broadcast in the background.

    Scheduled by the create endpoint via scheduler.add_job(...), so the HTTP
    request returns immediately. A Redis lock keyed on the broadcast id prevents
    duplicate execution across instances.
    """
    lock_key = CacheKey.user_broadcast_lock(broadcast_id)
    acquired = await redis_client.set_nx(lock_key, "1", ttl=LOCK_TTL)
    if not acquired:
        logger.debug("user_broadcast_skipped", reason="lock_held", broadcast_id=broadcast_id)
        return

    try:
        bot = get_bot()
        async with AsyncSessionFactory() as session:
            svc = UserBroadcastService(session, bot)
            await svc.run_broadcast(uuid.UUID(broadcast_id))
    except Exception as exc:
        logger.error("user_broadcast_job_failed", error=str(exc), broadcast_id=broadcast_id)
    finally:
        await redis_client.delete(lock_key)
