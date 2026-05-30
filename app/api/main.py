import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI

from app.api.admin import admin_router
from app.api.routers.health import router as health_router
from app.api.routers.webhook import create_webhook_router
from app.bot.main import create_bot, create_dispatcher, setup_webhook
from app.cache.client import redis_client
from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.schedulers.setup import create_scheduler

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    setup_logging()
    logger.info("application_starting", environment=settings.ENVIRONMENT)

    # Redis
    await redis_client.connect()

    # Bot
    bot = create_bot()
    dp = create_dispatcher()
    await setup_webhook(bot)

    # Scheduler
    scheduler = create_scheduler()
    scheduler.start()

    # Run initial slot generation on startup — force=True clears any stale lock
    from app.schedulers.jobs.slot_generation import generate_upcoming_slots
    await generate_upcoming_slots(force=True)

    # Store references in app state
    app.state.bot = bot
    app.state.dp = dp
    app.state.scheduler = scheduler

    polling_task: asyncio.Task | None = None

    if settings.WEBHOOK_URL:
        # Production: register webhook router so Telegram can POST updates
        webhook_router = create_webhook_router(bot, dp)
        app.include_router(webhook_router)
        logger.info("mode", value="webhook")
    else:
        # No public URL: start long-polling as a background asyncio task
        polling_task = asyncio.create_task(
            dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types()),
            name="bot_polling",
        )
        logger.info("mode", value="polling")

    logger.info("application_started")
    yield

    # ── Shutdown ───────────────────────────────────────────────────────────
    logger.info("application_stopping")

    if polling_task and not polling_task.done():
        polling_task.cancel()
        try:
            await polling_task
        except asyncio.CancelledError:
            pass

    scheduler.shutdown(wait=False)
    await bot.session.close()
    await redis_client.disconnect()
    logger.info("application_stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="19-Step Reservation Bot",
        version="1.0.0",
        docs_url="/docs" if settings.DEBUG else None,
        redoc_url=None,
        lifespan=lifespan,
    )

    app.include_router(health_router)
    app.include_router(admin_router)

    return app


app = create_app()
