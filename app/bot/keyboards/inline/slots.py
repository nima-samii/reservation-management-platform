import pytz
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.core.config import settings
from app.db.models.slot import ReservationSlot

TZ = pytz.timezone(settings.TIMEZONE)


def _time_label(slot: ReservationSlot) -> str:
    return slot.slot_datetime.astimezone(TZ).strftime("%I:%M %p")


def _chunk(lst: list, size: int) -> list[list]:
    return [lst[i : i + size] for i in range(0, len(lst), size)]


def build_slot_keyboard_grouped(
    recommended: list[ReservationSlot],
    more_available: list[ReservationSlot],
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    if recommended:
        rows.append([InlineKeyboardButton(text="📌 Recommended Slots", callback_data="section:recommended")])
        for chunk in _chunk(recommended, 3):
            rows.append([
                InlineKeyboardButton(text=_time_label(s), callback_data=f"slot:{s.id}")
                for s in chunk
            ])

    if more_available:
        rows.append([InlineKeyboardButton(text="➕ More Available Slots", callback_data="section:more")])
        for chunk in _chunk(more_available, 3):
            rows.append([
                InlineKeyboardButton(text=_time_label(s), callback_data=f"slot:{s.id}")
                for s in chunk
            ])

    rows.append([
        InlineKeyboardButton(text="⬅️ Back", callback_data="reservation:back_to_dates"),
        InlineKeyboardButton(text="❌ Cancel", callback_data="reservation:cancel"),
    ])

    return InlineKeyboardMarkup(inline_keyboard=rows)
