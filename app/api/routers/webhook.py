from aiogram import Bot, Dispatcher
from aiogram.types import Update
from fastapi import APIRouter, Header, HTTPException, Request

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["webhook"])


def create_webhook_router(bot: Bot, dp: Dispatcher) -> APIRouter:
    @router.post(settings.WEBHOOK_PATH)
    async def handle_webhook(
        request: Request,
        x_telegram_bot_api_secret_token: str | None = Header(default=None),
    ) -> dict:
        if settings.WEBHOOK_SECRET:
            if x_telegram_bot_api_secret_token != settings.WEBHOOK_SECRET:
                raise HTTPException(status_code=403, detail="Forbidden")

        body = await request.json()
        update = Update.model_validate(body, context={"bot": bot})
        await dp.feed_update(bot, update)
        return {"ok": True}

    return router
