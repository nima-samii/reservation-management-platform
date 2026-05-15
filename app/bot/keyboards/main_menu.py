from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


class MainMenuButton:
    RESERVE = "📅 Reserve Time"
    MY_RESERVATIONS = "📋 My Reservations"
    EDIT_PROFILE = "✏️ Edit Profile"
    HELP = "❓ Help"


def get_main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text=MainMenuButton.RESERVE),
                KeyboardButton(text=MainMenuButton.MY_RESERVATIONS),
            ],
            [
                KeyboardButton(text=MainMenuButton.EDIT_PROFILE),
                KeyboardButton(text=MainMenuButton.HELP),
            ],
        ],
        resize_keyboard=True,
        persistent=True,
    )
