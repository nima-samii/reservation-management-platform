import pytz
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.core.config import settings
from app.db.models.slot import ReservationSlot

TZ = pytz.timezone(settings.TIMEZONE)

# Callback prefixes. `slot:` names one physical row; `lslot:` names a local
# clock time and lets the booking pick the channel. Both are accepted by the
# handlers — a keyboard already sitting in a user's chat keeps working after a
# strategy switch, in whichever direction.
SLOT_CALLBACK_PREFIX = "slot:"
LOGICAL_SLOT_CALLBACK_PREFIX = "lslot:"


def _time_label(slot: ReservationSlot) -> str:
    return slot.slot_datetime.astimezone(TZ).strftime("%I:%M %p")


def _callback_time(slot: ReservationSlot) -> str:
    """24-hour HH:MM — the button label is 12-hour and would be ambiguous."""
    return slot.slot_datetime.astimezone(TZ).strftime("%H:%M")


def _chunk(lst: list, size: int) -> list[list]:
    return [lst[i : i + size] for i in range(0, len(lst), size)]


def build_slot_keyboard_grouped(
    recommended: list[ReservationSlot],
    more_available: list[ReservationSlot],
    *,
    by_time: bool = False,
) -> InlineKeyboardMarkup:
    """Slot buttons, in one or two sections.

    ``by_time`` switches the callback data from ``slot:{uuid}`` to
    ``lslot:HH:MM``, for strategies that choose the channel at booking time.
    The date is not in the callback: it is already in the FSM, put there by the
    date step that produced this very keyboard, and 64 bytes of callback data
    is a budget worth not spending twice.

    That mode also drops the section headers. They label *channel groupings*
    ("Recommended" vs "More Available"), and a strategy that resolves by time
    has no second section and never asks the user to choose a channel — so a
    lone "📌 Recommended Slots" header would imply a distinction that does not
    exist. Identity mode renders exactly as before.
    """
    prefix = LOGICAL_SLOT_CALLBACK_PREFIX if by_time else SLOT_CALLBACK_PREFIX

    def _button(slot: ReservationSlot) -> InlineKeyboardButton:
        target = _callback_time(slot) if by_time else slot.id
        return InlineKeyboardButton(text=_time_label(slot), callback_data=f"{prefix}{target}")

    rows: list[list[InlineKeyboardButton]] = []

    if recommended:
        if not by_time:
            rows.append([InlineKeyboardButton(text="📌 Recommended Slots", callback_data="section:recommended")])
        for chunk in _chunk(recommended, 3):
            rows.append([_button(s) for s in chunk])

    if more_available:
        if not by_time:
            rows.append([InlineKeyboardButton(text="➕ More Available Slots", callback_data="section:more")])
        for chunk in _chunk(more_available, 3):
            rows.append([_button(s) for s in chunk])

    rows.append([
        InlineKeyboardButton(text="⬅️ Back", callback_data="reservation:back_to_dates"),
        InlineKeyboardButton(text="❌ Cancel", callback_data="reservation:cancel"),
    ])

    return InlineKeyboardMarkup(inline_keyboard=rows)
