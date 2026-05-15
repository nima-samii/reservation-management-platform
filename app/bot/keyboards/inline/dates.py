from datetime import date

import pytz
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.core.config import settings

TZ = pytz.timezone(settings.TIMEZONE)

WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTH_NAMES = [
    "", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"
]


def build_date_keyboard(available_dates: list[date]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    for d in available_dates:
        weekday = WEEKDAY_NAMES[d.weekday()]
        label = f"{weekday}, {d.day} {MONTH_NAMES[d.month]}"
        builder.button(
            text=label,
            callback_data=f"date:{d.isoformat()}",
        )

    builder.button(text="❌ Cancel", callback_data="reservation:cancel")
    builder.adjust(2)
    return builder.as_markup()
