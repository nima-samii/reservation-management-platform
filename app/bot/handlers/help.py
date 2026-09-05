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
    "ℹ️ *19-Steps Toward Inner Peace Bot — Help*\n\n"
    "📅 *Reserve Time*\n"
    "Book a 30-minute live Toward Inner Peace session.\n"
    f"• Sessions run 4:00 PM – 12:00 AM ({settings.TIMEZONE})\n"
    f"• Max {settings.MAX_ACTIVE_RESERVATIONS} active reservations at a time\n"
    f"{_daily_limit_line()}\n"
    "• Same-day booking closes at 12:00 PM noon\n\n"
    "📋 *My Reservations*\n"
    "View and manage your upcoming sessions.\n"
    "You can cancel any future reservation before 12:00 PM noon on the day of the session.\n\n"
    "🎯 *Score Calculation System*\n"
    "📺 *Hosting a Live Broadcast*: You earn points equal to the number of "
    "participants in each live broadcast.\n"
    "👤 *Referring someone to the “19 Steps” Course* and hosting their live "
    "broadcast: You earn 30 points.\n"
    "🤝 *Joint Live Broadcast*: If you host a joint live broadcast with another "
    "person as part of your broadcast, your points are doubled.\n"
    "🏛 *Conducting an in-person “19 Steps” Course*: You earn points equal to the "
    "number of participants in the course.\n\n"
    "These are awarded by an admin after the activity — you don't need to claim them.\n\n"
    "⭐ *After each session*\n"
    "An admin reviews the session once it has finished and records whether you "
    "took part, the points it earned you, and a short note explaining the "
    "decision. You get a message with all three.\n"
    "• Booking a session does not change your score\n"
    "• Cancelling a session does not change your score\n"
    "Your score reflects what you actually took part in, not how often you booked.\n\n"
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
