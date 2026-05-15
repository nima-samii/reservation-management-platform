import uuid
from datetime import date

import pytz
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.inline.dates import build_date_keyboard
from app.bot.keyboards.inline.slots import build_slot_keyboard
from app.bot.keyboards.main_menu import MainMenuButton, get_main_menu
from app.bot.states.reservation import ReservationSG
from app.cache.client import redis_client
from app.core.config import settings
from app.core.exceptions import (
    DailyLimitError,
    MaxReservationsError,
    NoChannelAvailableError,
    NotFoundError,
    PastSlotError,
    SlotUnavailableError,
)
from app.core.logging import get_logger
from app.db.models.user import User
from app.services.reservation import ReservationService
from app.services.slot import SlotService

logger = get_logger(__name__)
router = Router(name="reservation")

TZ = pytz.timezone(settings.TIMEZONE)


@router.message(F.text == MainMenuButton.RESERVE)
async def start_reservation(message: Message, state: FSMContext, session: AsyncSession, db_user: User | None) -> None:
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
async def choose_date(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await callback.answer()
    date_str = callback.data.split(":", 1)[1]  # type: ignore[union-attr]

    try:
        selected_date = date.fromisoformat(date_str)
    except ValueError:
        await callback.answer("Invalid date selected.", show_alert=True)
        return

    slot_svc = SlotService(session)
    slots = await slot_svc.get_available_slots_for_date(selected_date)

    if not slots:
        await callback.answer(
            "No available slots for this date. Please pick another.", show_alert=True
        )
        return

    await state.update_data(selected_date=date_str)

    await callback.message.edit_text(  # type: ignore[union-attr]
        f"🕐 *Available slots for {selected_date.strftime('%A, %d %B')}:*\n\n"
        "Select a time slot:",
        reply_markup=build_slot_keyboard(slots, selected_date),
        parse_mode="Markdown",
    )
    await state.set_state(ReservationSG.choose_slot)


@router.callback_query(ReservationSG.choose_slot, F.data == "reservation:back_to_dates")
async def back_to_dates(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await callback.answer()
    slot_svc = SlotService(session)
    available_dates = await slot_svc.get_available_dates()

    await callback.message.edit_text(  # type: ignore[union-attr]
        "📅 *Select a date for your reservation:*",
        reply_markup=build_date_keyboard(available_dates),
        parse_mode="Markdown",
    )
    await state.set_state(ReservationSG.choose_date)


@router.callback_query(ReservationSG.choose_slot, F.data.startswith("slot:"))
async def choose_slot(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    db_user: User | None,
) -> None:
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

    from app.db.models.slot import ReservationSlot
    from app.repositories.slot import SlotRepository
    slot_repo = SlotRepository(session)
    slot = await slot_repo.get_by_id(slot_id)

    if not slot:
        await callback.answer("This slot no longer exists.", show_alert=True)
        return

    local_dt = slot.slot_datetime.astimezone(TZ)
    date_str = local_dt.strftime("%A, %d %B")
    time_str = local_dt.strftime("%I:%M %p")

    await state.update_data(slot_id=str(slot_id))

    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
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
        f"📅 Date: *{date_str}*\n"
        f"🕐 Time: *{time_str}*\n\n"
        "Confirm your reservation?",
        reply_markup=confirm_kb,
        parse_mode="Markdown",
    )
    await state.set_state(ReservationSG.confirm)


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
    slot_id_str = data.get("slot_id", "")

    try:
        slot_id = uuid.UUID(slot_id_str)
    except ValueError:
        await callback.answer("Session expired. Please start again.", show_alert=True)
        await state.clear()
        return

    svc = ReservationService(session, redis_client)

    try:
        reservation = await svc.book_slot(
            telegram_id=db_user.telegram_id,
            slot_id=slot_id,
        )
    except SlotUnavailableError:
        await callback.message.edit_text(  # type: ignore[union-attr]
            "❌ *Slot Unavailable*\n\n"
            "This slot was just booked by someone else.\n"
            "Please go back and choose another slot.",
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
    except NoChannelAvailableError:
        await callback.message.edit_text(  # type: ignore[union-attr]
            "😕 No channels are available right now. Please try again later.",
            parse_mode="Markdown",
        )
        await state.clear()
        return

    slot_dt = reservation.slot.slot_datetime.astimezone(TZ)

    await callback.message.edit_text(  # type: ignore[union-attr]
        f"🎉 *Reservation Confirmed!*\n\n"
        f"📅 {slot_dt.strftime('%A, %d %B %Y')}\n"
        f"🕐 {slot_dt.strftime('%I:%M %p')}\n"
        f"📡 Channel: {reservation.channel.name}\n\n"
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
