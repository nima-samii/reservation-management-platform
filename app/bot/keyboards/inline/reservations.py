import uuid

import pytz
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.core.config import settings
from app.db.models.reservation import Reservation

TZ = pytz.timezone(settings.TIMEZONE)


def build_reservations_keyboard(
    reservations: list[Reservation],
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    for res in reservations:
        local_dt = res.slot.slot_datetime.astimezone(TZ)
        date_str = local_dt.strftime("%a %d %b")
        time_str = local_dt.strftime("%I:%M %p")
        builder.button(
            text=f"🗓 {date_str} • {time_str}",
            callback_data=f"res_view:{res.id}",
        )

    builder.adjust(1)
    return builder.as_markup()


def build_reservation_detail_keyboard(
    reservation_id: uuid.UUID,
    can_cancel: bool,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    if can_cancel:
        builder.button(
            text="❌ Cancel Reservation",
            callback_data=f"res_cancel:{reservation_id}",
        )

    builder.button(text="⬅️ Back", callback_data="reservations:list")
    builder.adjust(1)
    return builder.as_markup()


def build_cancel_confirm_keyboard(reservation_id: uuid.UUID) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Yes, cancel it",
        callback_data=f"res_cancel_confirm:{reservation_id}",
    )
    builder.button(
        text="⬅️ No, keep it",
        callback_data=f"res_view:{reservation_id}",
    )
    builder.adjust(1)
    return builder.as_markup()
