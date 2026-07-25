from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.core.config import settings

CHECK_MEMBERSHIP_CALLBACK = "check_membership"

MEMBERSHIP_REQUIRED_TEXT = (
    "🔒 *Membership required*\n\n"
    "To use this bot, please join all required channels first, "
    "then tap *✅ Check Membership*."
)

MEMBERSHIP_SUCCESS_TEXT = (
    "✅ *Thanks for joining!*\n\n"
    "You now have full access. Send /start to begin."
)

MEMBERSHIP_NOT_JOINED_ALERT = "You have not joined all required channels yet."

# Short, plain-text version shown as a popup alert when there is no chat
# message to post the full prompt into (e.g. callbacks on inline messages).
MEMBERSHIP_REQUIRED_ALERT = (
    "🔒 Please join all required channels first, then tap Check Membership."
)


def build_membership_keyboard() -> InlineKeyboardMarkup:
    """One 'Join Channel N' button per configured channel + a check button."""
    builder = InlineKeyboardBuilder()

    for idx, channel in enumerate(settings.required_channels, start=1):
        if channel.url:
            builder.button(text=f"Join Channel {idx}", url=channel.url)

    builder.button(text="✅ Check Membership", callback_data=CHECK_MEMBERSHIP_CALLBACK)
    builder.adjust(1)
    return builder.as_markup()
