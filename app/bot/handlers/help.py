from aiogram import F, Router
from aiogram.types import Message

from app.bot.keyboards.main_menu import MainMenuButton, get_main_menu
from app.core.config import settings

router = Router(name="help")

def _daily_limit_line() -> str:
    """"One per day" is a different sentence from "up to N per day"."""
    cap = settings.MAX_DAILY_RESERVATIONS
    if cap == 1:
        return "• One reservation per day"
    return f"• Up to {cap} reservations per day"


def build_help_text() -> str:
    """Rendered per request rather than frozen in a module constant.

    Both caps quoted below are admin-editable and take effect without a
    restart, so a constant built at import time would keep telling users
    whatever the limits were when the process started.

    The session hours and the two 12:00 PM cutoffs are still literals here even
    though SLOT_START_HOUR / SLOT_END_HOUR / SAME_DAY_CUTOFF_HOUR /
    SAME_DAY_CANCEL_CUTOFF_HOUR are editable too — they need 24h-to-12h
    formatting this change does not introduce.
    """
    return (
    "ℹ️ *19-Step English Learning Bot — Help*\n\n"
    "📅 *Reserve Time*\n"
    "Book a 30-minute live English session.\n"
    f"• Sessions run 4:00 PM – 12:00 AM ({settings.TIMEZONE})\n"
    f"• Max {settings.MAX_ACTIVE_RESERVATIONS} active reservations at a time\n"
    f"{_daily_limit_line()}\n"
    "• Same-day booking closes at 12:00 PM noon\n\n"
    "📋 *My Reservations*\n"
    "View and manage your upcoming sessions.\n"
    "You can cancel any future reservation before 12:00 PM noon on the day of the session.\n\n"
    "⭐ *Participation Score*\n"
    "Your score reflects your engagement with the program:\n"
    "• *+1* when you successfully reserve a session\n"
    "• *−1* if you cancel a reservation\n"
    "• Future penalties may apply for no-shows\n"
    "A higher score reflects consistent participation and builds your reputation in the community.\n\n"
    "✏️ *Edit Profile*\n"
    "Update your name, gender, or country.\n"
    "Your Participation Score is visible in your profile.\n\n"
    "🔑 *Your User ID*\n"
    "Your unique 6-digit code is shown on the main screen.\n\n"
    "Need support? Contact the admin."
    )


@router.message(F.text == MainMenuButton.HELP)
async def show_help(message: Message) -> None:
    await message.answer(
        build_help_text(),
        reply_markup=get_main_menu(),
        parse_mode="Markdown",
    )
