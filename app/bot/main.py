from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage

from app.bot.handlers import help, my_reservations, profile, registration, reservation, start
from app.bot.middlewares.anti_flood import AntiFloodMiddleware
from app.bot.middlewares.db_session import DbSessionMiddleware
from app.bot.middlewares.rate_limit import RateLimitMiddleware
from app.bot.middlewares.user_context import UserContextMiddleware
from app.cache.client import redis_client
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def create_bot() -> Bot:
    return Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def create_dispatcher() -> Dispatcher:
    storage = RedisStorage.from_url(settings.redis_url)
    dp = Dispatcher(storage=storage)

    # ── Middlewares (order matters: outer → inner) ──────────────────────────
    dp.update.outer_middleware(AntiFloodMiddleware())
    dp.update.outer_middleware(RateLimitMiddleware())
    dp.update.outer_middleware(DbSessionMiddleware())
    dp.update.outer_middleware(UserContextMiddleware())

    # ── Routers ────────────────────────────────────────────────────────────
    dp.include_router(start.router)
    dp.include_router(registration.router)
    dp.include_router(reservation.router)
    dp.include_router(my_reservations.router)
    dp.include_router(profile.router)
    dp.include_router(help.router)

    return dp


async def setup_webhook(bot: Bot) -> None:
    if settings.WEBHOOK_URL:
        webhook_url = f"{settings.WEBHOOK_URL}{settings.WEBHOOK_PATH}"
        await bot.set_webhook(
            url=webhook_url,
            secret_token=settings.WEBHOOK_SECRET,
            drop_pending_updates=True,
        )
        logger.info("webhook_set", url=webhook_url)
    else:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("webhook_deleted", mode="polling")
