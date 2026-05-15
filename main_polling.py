"""
Development entrypoint — runs the bot in polling mode (no webhook needed).
Usage: python main_polling.py
"""
import asyncio

from app.bot.main import create_bot, create_dispatcher
from app.cache.client import redis_client
from app.core.logging import get_logger, setup_logging
from app.schedulers.jobs.slot_generation import generate_upcoming_slots
from app.schedulers.setup import create_scheduler

logger = get_logger(__name__)


async def main() -> None:
    setup_logging()
    logger.info("starting_polling_mode")

    await redis_client.connect()

    bot = create_bot()
    dp = create_dispatcher()

    await bot.delete_webhook(drop_pending_updates=True)

    scheduler = create_scheduler()
    scheduler.start()

    await generate_upcoming_slots()

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()
        await redis_client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
