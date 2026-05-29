from aiogram import Bot

from app.bot.main import create_bot

_bot: Bot | None = None


def get_bot() -> Bot:
    """Return the shared Bot instance, creating it on first call."""
    global _bot
    if _bot is None:
        _bot = create_bot()
    return _bot
