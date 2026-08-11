import uuid
from datetime import date, datetime

import pytz
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.inline.dates import build_date_keyboard
from app.bot.keyboards.inline.slots import build_slot_keyboard_grouped
from app.bot.keyboards.main_menu import MainMenuButton, get_main_menu
from app.bot.states.reservation import ReservationSG
from app.cache.client import redis_client
from app.core.config import settings
from app.core.exceptions import (
    DailyLimitError,
    MaxReservationsError,
    NotFoundError,
    PastSlotError,
    SameDayCutoffError,
    SlotUnavailableError,
)
from app.core.logging import get_logger
from app.db.models.user import User
from app.repositories.slot import SlotRepository
from app.services.reservation import ReservationService
from app.services.slot import SlotService
from app.services.strategies.base import SlotRef

logger = get_logger(__name__)
router = Router(name="reservation")

TZ = pytz.timezone(settings.TIMEZONE)


@router.message(F.text == MainMenuButton.RESERVE)
async def start_reservation(
    message: Message, state: FSMContext, session: AsyncSession, db_user: User | None
) -> None:
    if not db_user:
        await message.answer("Please register first with /start")
        return

    slot_svc = SlotService(session)
    available_dates = await slot_svc.get_available_dates()

    if not available_dates:
        await message.answer(
            "😕 No available time slots found for the next "
            f"{settings.MAX_RESERVATION_DAYS_AHEAD} days.\n\n"
            "Please check back later.",
            reply_markup=get_main_menu(),
        )
        return

    await message.answer(
        "📅 *Select a date for your reservation:*\n\n"
        f"Available for the next {settings.MAX_RESERVATION_DAYS_AHEAD} days.",
        reply_markup=build_date_keyboard(available_dates),
        parse_mode="Markdown",
    )
    await state.set_state(ReservationSG.choose_date)


@router.callback_query(ReservationSG.choose_date, F.data.startswith("date:"))
async def choose_date(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    await callback.answer()
    date_str = callback.data.split(":", 1)[1]  # type: ignore[union-attr]

    try:
        selected_date = date.fromisoformat(date_str)
    except ValueError:
        await callback.answer("Invalid date selected.", show_alert=True)
        return

    slot_svc = SlotService(session)
    grouped = await slot_svc.get_available_slots_for_date_grouped(selected_date)

    if not grouped["recommended"] and not grouped["more_available"]:
        await callback.answer(
            "No available slots for this date. Please pick another.", show_alert=True
        )
        return

    await state.update_data(selected_date=date_str)

    more_count = len(grouped["more_available"])
    subtitle = ""
    if more_count:
        subtitle = f"\n_+{more_count} more slots available from additional channels_"

    await callback.message.edit_text(  # type: ignore[union-attr]
        f"🕐 *Available slots for {selected_date.strftime('%A, %d %B')}:*{subtitle}\n\n"
        "Select a time slot:",
        reply_markup=build_slot_keyboard_grouped(
            grouped["recommended"],
            grouped["more_available"],
            by_time=slot_svc.offers_slots_by_time(),
        ),
        parse_mode="Markdown",
    )
    await state.set_state(ReservationSG.choose_slot)


@router.callback_query(F.data.startswith("section:"))
async def section_header_noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(ReservationSG.choose_slot, F.data == "reservation:back_to_dates")
async def back_to_dates(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    await callback.answer()
    slot_svc = SlotService(session)
    available_dates = await slot_svc.get_available_dates()

    await callback.message.edit_text(  # type: ignore[union-attr]
        "📅 *Select a date for your reservation:*",
        reply_markup=build_date_keyboard(available_dates),
        parse_mode="Markdown",
    )
    await state.set_state(ReservationSG.choose_date)


async def _show_confirmation(callback: CallbackQuery, state: FSMContext, local_dt: datetime) -> None:
    """Render the summary step. Identical for both callback forms — the user is
    confirming a date and a time either way; which channel it lands on is not
    something they were ever shown here."""
    confirm_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Confirm", callback_data="reservation:confirm"),
                InlineKeyboardButton(text="❌ Cancel", callback_data="reservation:cancel"),
            ]
        ]
    )

    await callback.message.edit_text(  # type: ignore[union-attr]
        f"📋 *Reservation Summary*\n\n"
        f"📅 Date: *{local_dt.strftime('%A, %d %B')}*\n"
        f"🕐 Time: *{local_dt.strftime('%I:%M %p')}*\n\n"
        "Confirm your reservation?",
        reply_markup=confirm_kb,
        parse_mode="Markdown",
    )
    await state.set_state(ReservationSG.confirm)


def _slot_ref_from_state(data: dict) -> SlotRef | None:
    """Recover what the user tapped, in whichever form it was stored.

    Exactly one of the two keys is ever set — each handler clears the other —
    so the order below is not a precedence rule, just a lookup. Returning None
    covers both an empty FSM and an unparseable value; the caller treats both
    as an expired session, which is what they are.
    """
    raw_time = data.get("slot_time")
    if raw_time:
        try:
            return datetime.fromisoformat(raw_time)
        except (TypeError, ValueError):
            return None

    raw_id = data.get("slot_id")
    if raw_id:
        try:
            return uuid.UUID(raw_id)
        except (TypeError, ValueError):
            return None

    return None


@router.callback_query(ReservationSG.choose_slot, F.data.startswith("slot:"))
async def choose_slot(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    db_user: User | None,
) -> None:
    """A button naming one physical slot row.

    Still the live format under THRESHOLD_UNLOCK, and still accepted under
    SEQUENTIAL_FILL — a user may have a keyboard from before the switch, and
    that strategy reads such a reference for its time. Kept as its own handler
    rather than folded into the logical one because the two really do carry
    different information, and only this one can check the row exists up front.
    """
    await callback.answer()

    if not db_user:
        await callback.answer("Please register first.", show_alert=True)
        return

    slot_id_str = callback.data.split(":", 1)[1]  # type: ignore[union-attr]

    try:
        slot_id = uuid.UUID(slot_id_str)
    except ValueError:
        await callback.answer("Invalid slot.", show_alert=True)
        return

    slot_repo = SlotRepository(session)
    slot = await slot_repo.get_by_id(slot_id)

    if not slot:
        await callback.answer("This slot no longer exists.", show_alert=True)
        return

    await state.update_data(slot_id=str(slot_id), slot_time=None)
    await _show_confirmation(callback, state, slot.slot_datetime.astimezone(TZ))


@router.callback_query(ReservationSG.choose_slot, F.data.startswith("lslot:"))
async def choose_logical_slot(
    callback: CallbackQuery,
    state: FSMContext,
    db_user: User | None,
) -> None:
    """A button naming a local clock time, with the channel left to the booking.

    The date comes from the FSM rather than the callback. That is safe here and
    not merely convenient: this handler is state-filtered on ``choose_slot``,
    and the only transition into that state is ``choose_date``, which writes
    ``selected_date`` in the same step. No date in state means no such
    transition happened, which is an expired session.

    Nothing is looked up yet. Which row this becomes is decided under a lock at
    confirm time, and querying now would only produce an answer that is allowed
    to be stale by the time it matters.
    """
    await callback.answer()

    if not db_user:
        await callback.answer("Please register first.", show_alert=True)
        return

    time_str = callback.data.split(":", 1)[1]  # type: ignore[union-attr]
    data = await state.get_data()

    try:
        slot_date = date.fromisoformat(data.get("selected_date", ""))
        hour, minute = (int(part) for part in time_str.split(":"))
        local_dt = TZ.localize(
            datetime(slot_date.year, slot_date.month, slot_date.day, hour, minute)
        )
    except (ValueError, TypeError):
        await callback.answer("Session expired. Please start again.", show_alert=True)
        await state.clear()
        return

    await state.update_data(slot_time=local_dt.isoformat(), slot_id=None)
    await _show_confirmation(callback, state, local_dt)


@router.callback_query(ReservationSG.confirm, F.data == "reservation:confirm")
async def confirm_reservation(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    db_user: User | None,
) -> None:
    await callback.answer()

    if not db_user:
        await callback.answer("Please register first.", show_alert=True)
        return

    data = await state.get_data()
    slot_ref = _slot_ref_from_state(data)

    if slot_ref is None:
        await callback.answer("Session expired. Please start again.", show_alert=True)
        await state.clear()
        return

    svc = ReservationService(session, redis_client)

    try:
        reservation = await svc.book_slot(
            telegram_id=db_user.telegram_id,
            slot_ref=slot_ref,
        )
    except SlotUnavailableError:
        fsm_data = await state.get_data()
        date_str = fsm_data.get("selected_date", "")
        if date_str:
            retry_kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="🔄 Pick Another Slot",
                    callback_data=f"date:{date_str}",
                ),
                InlineKeyboardButton(text="❌ Cancel", callback_data="reservation:cancel"),
            ]])
            await callback.message.edit_text(  # type: ignore[union-attr]
                "⚡ *Slot No Longer Available*\n\n"
                "Someone else just booked this time slot.\n"
                "Please pick a different time.",
                reply_markup=retry_kb,
                parse_mode="Markdown",
            )
            await state.set_state(ReservationSG.choose_date)
        else:
            await callback.message.edit_text(  # type: ignore[union-attr]
                "⚡ *Slot No Longer Available*\n\n"
                "Someone else just booked this time slot.\n"
                "Please start over and pick a different time.",
                parse_mode="Markdown",
            )
            await state.clear()
        return
    except DailyLimitError:
        await callback.message.edit_text(  # type: ignore[union-attr]
            "⚠️ *Daily Limit Reached*\n\n"
            "You already have a reservation on this day.\n"
            "Only one reservation per day is allowed.",
            parse_mode="Markdown",
        )
        await state.clear()
        return
    except MaxReservationsError as e:
        await callback.message.edit_text(  # type: ignore[union-attr]
            f"⚠️ *Reservation Limit*\n\n{e.message}",
            parse_mode="Markdown",
        )
        await state.clear()
        return
    except PastSlotError:
        await callback.message.edit_text(  # type: ignore[union-attr]
            "⚠️ This slot has already passed.",
            parse_mode="Markdown",
        )
        await state.clear()
        return
    except SameDayCutoffError as e:
        await callback.message.edit_text(  # type: ignore[union-attr]
            f"⏰ *Reservations Closed for Today*\n\n"
            f"{e.message}\n\n"
            "Please choose a slot for tomorrow or a later date.",
            parse_mode="Markdown",
        )
        await state.clear()
        return

    slot_dt = reservation.slot.slot_datetime.astimezone(TZ)
    invite_line = f"\n🔗 [Join Channel]({reservation.channel.invite_link})" if reservation.channel.invite_link else ""

    await callback.message.edit_text(  # type: ignore[union-attr]
        f"🎉 *Reservation Confirmed!*\n\n"
        f"📅 {slot_dt.strftime('%A, %d %B %Y')}\n"
        f"🕐 {slot_dt.strftime('%I:%M %p')}\n"
        f"📡 Channel: {reservation.channel.name}"
        f"{invite_line}\n\n"
        f"🔑 Reservation ID: `{str(reservation.id)[:8]}...`\n\n"
        "You can view or cancel this under *My Reservations*.",
        parse_mode="Markdown",
    )

    await callback.message.answer(  # type: ignore[union-attr]
        "📌 Main Menu",
        reply_markup=get_main_menu(),
    )
    await state.clear()


@router.callback_query(F.data == "reservation:cancel")
async def cancel_reservation_flow(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer("Cancelled.")
    await state.clear()
    await callback.message.edit_text("❌ Reservation flow cancelled.")  # type: ignore[union-attr]
