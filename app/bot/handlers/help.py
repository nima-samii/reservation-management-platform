from aiogram import F, Router
from aiogram.types import Message

from app.bot.keyboards.main_menu import MainMenuButton, get_main_menu
from app.core.config import settings

router = Router(name="help")

HELP_TEXT = (
    "ℹ️ *19-Step English Learning Bot — Help*\n\n"
    "📅 *Reserve Time*\n"
    "Book a 30-minute live English session.\n"
    f"• Sessions run 4:00 PM – 12:00 AM ({settings.TIMEZONE})\n"
    f"• Max {settings.MAX_ACTIVE_RESERVATIONS} active reservations at a time\n"
    "• One reservation per day\n"
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
        HELP_TEXT,
        reply_markup=get_main_menu(),
        parse_mode="Markdown",
    )
