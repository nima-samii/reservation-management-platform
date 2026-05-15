from datetime import date

import pytz
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.core.config import settings
from app.db.models.slot import ReservationSlot

TZ = pytz.timezone(settings.TIMEZONE)


def build_slot_keyboard(
    slots: list[ReservationSlot], selected_date: date
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    for slot in slots:
        local_dt = slot.slot_datetime.astimezone(TZ)
        label = local_dt.strftime("%I:%M %p")
        builder.button(
            text=label,
            callback_data=f"slot:{slot.id}",
        )

    builder.button(text="⬅️ Back", callback_data="reservation:back_to_dates")
    builder.button(text="❌ Cancel", callback_data="reservation:cancel")
    builder.adjust(3)
    return builder.as_markup()
