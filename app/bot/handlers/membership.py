from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery

from app.bot.keyboards.inline.membership import (
    CHECK_MEMBERSHIP_CALLBACK,
    MEMBERSHIP_NOT_JOINED_ALERT,
    MEMBERSHIP_SUCCESS_TEXT,
)
from app.core.logging import get_logger
from app.services.membership import MembershipService

logger = get_logger(__name__)
router = Router(name="membership")


@router.callback_query(F.data == CHECK_MEMBERSHIP_CALLBACK)
async def check_membership(callback: CallbackQuery, bot: Bot) -> None:
    service = MembershipService(bot)
    is_member = await service.check_user_membership(callback.from_user.id)

    if not is_member:
        await callback.answer(MEMBERSHIP_NOT_JOINED_ALERT, show_alert=True)
        return

    logger.info("membership_gate_passed", telegram_id=callback.from_user.id)
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            MEMBERSHIP_SUCCESS_TEXT, parse_mode="Markdown"
        )
