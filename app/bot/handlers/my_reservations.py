import uuid
from datetime import datetime

import pytz
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.inline.reservations import (
    build_cancel_confirm_keyboard,
    build_reservation_detail_keyboard,
    build_reservations_keyboard,
)
from app.bot.keyboards.main_menu import MainMenuButton, get_main_menu
from app.cache.client import redis_client
from app.core.booking_rules import can_cancel_reservation
from app.core.config import settings
from app.core.exceptions import CancellationCutoffError, NotFoundError, PastSlotError
from app.core.logging import get_logger
from app.db.models.user import User
from app.services.reservation import ReservationService

logger = get_logger(__name__)
router = Router(name="my_reservations")

TZ = pytz.timezone(settings.TIMEZONE)


@router.message(F.text == MainMenuButton.MY_RESERVATIONS)
@router.callback_query(F.data == "reservations:list")
async def my_reservations(
    event: Message | CallbackQuery,
    session: AsyncSession,
    db_user: User | None,
    state: FSMContext,
) -> None:
    if not db_user:
        target = event if isinstance(event, Message) else event.message  # type: ignore[union-attr]
        await target.answer("Please register first with /start")  # type: ignore[union-attr]
        return

    svc = ReservationService(session, redis_client)
    reservations = await svc.get_user_reservations(db_user.telegram_id)

    if isinstance(event, CallbackQuery):
        await event.answer()

    if not reservations:
        text = (
            "📋 *My Reservations*\n\n"
            "You have no active reservations.\n\n"
            "Use *Reserve Time* to book a session!"
        )
        if isinstance(event, Message):
            await event.answer(text, reply_markup=get_main_menu(), parse_mode="Markdown")
        else:
            await event.message.edit_text(text, parse_mode="Markdown")  # type: ignore[union-attr]
        return

    text = f"📋 *My Reservations* ({len(reservations)} active)\n\nSelect one to view details:"
    kb = build_reservations_keyboard(reservations)

    if isinstance(event, Message):
        await event.answer(text, reply_markup=kb, parse_mode="Markdown")
    else:
        await event.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")  # type: ignore[union-attr]


@router.callback_query(F.data.startswith("res_view:"))
async def view_reservation(
    callback: CallbackQuery,
    session: AsyncSession,
    db_user: User | None,
) -> None:
    await callback.answer()

    res_id_str = callback.data.split(":", 1)[1]  # type: ignore[union-attr]
    try:
        res_id = uuid.UUID(res_id_str)
    except ValueError:
        await callback.answer("Invalid reservation.", show_alert=True)
        return

    svc = ReservationService(session, redis_client)

    from app.repositories.reservation import ReservationRepository
    repo = ReservationRepository(session)
    res = await repo.get_reservation_with_details(res_id)

    if not res or (db_user and res.user_id != db_user.id):
        await callback.answer("Reservation not found.", show_alert=True)
        return

    slot_dt = res.slot.slot_datetime.astimezone(TZ)
    now = datetime.now(TZ)
    can_cancel = can_cancel_reservation(slot_dt, now, settings.SAME_DAY_CANCEL_CUTOFF_HOUR)

    await callback.message.edit_text(  # type: ignore[union-attr]
        f"🗓 *Reservation Details*\n\n"
        f"📅 Date: *{slot_dt.strftime('%A, %d %B %Y')}*\n"
        f"🕐 Time: *{slot_dt.strftime('%I:%M %p')}*\n"
        f"📡 Channel: {res.channel.name}\n"
        f"🔖 Status: {res.status.upper()}\n\n"
        f"🔑 ID: `{str(res.id)[:8]}...`",
        reply_markup=build_reservation_detail_keyboard(res.id, can_cancel),
        parse_mode="Markdown",
    )


@router.callback_query(F.data.startswith("res_cancel:"))
async def cancel_reservation_prompt(
    callback: CallbackQuery,
    session: AsyncSession,
    db_user: User | None,
) -> None:
    await callback.answer()
    res_id_str = callback.data.split(":", 1)[1]  # type: ignore[union-attr]

    try:
        res_id = uuid.UUID(res_id_str)
    except ValueError:
        return

    await callback.message.edit_text(  # type: ignore[union-attr]
        "⚠️ *Cancel Reservation*\n\n"
        "Are you sure you want to cancel this reservation?\n"
        "This action cannot be undone.",
        reply_markup=build_cancel_confirm_keyboard(res_id),
        parse_mode="Markdown",
    )


@router.callback_query(F.data.startswith("res_cancel_confirm:"))
async def confirm_cancel_reservation(
    callback: CallbackQuery,
    session: AsyncSession,
    db_user: User | None,
) -> None:
    await callback.answer()

    if not db_user:
        await callback.answer("Not authorized.", show_alert=True)
        return

    res_id_str = callback.data.split(":", 1)[1]  # type: ignore[union-attr]
    try:
        res_id = uuid.UUID(res_id_str)
    except ValueError:
        return

    svc = ReservationService(session, redis_client)

    try:
        await svc.cancel_reservation(
            telegram_id=db_user.telegram_id,
            reservation_id=res_id,
        )
        await callback.message.edit_text(  # type: ignore[union-attr]
            "✅ *Reservation Cancelled*\n\n"
            "Your reservation has been successfully cancelled.\n"
            "The slot is now available for others.",
            parse_mode="Markdown",
        )
    except PastSlotError:
        await callback.message.edit_text(  # type: ignore[union-attr]
            "❌ Cannot cancel a past reservation.",
            parse_mode="Markdown",
        )
    except CancellationCutoffError as e:
        await callback.message.edit_text(  # type: ignore[union-attr]
            f"⏰ *Cancellation Not Allowed*\n\n"
            f"{e.message}\n\n"
            "Future-day reservations can still be cancelled.",
            parse_mode="Markdown",
        )
    except NotFoundError:
        await callback.message.edit_text(  # type: ignore[union-attr]
            "❌ Reservation not found.",
            parse_mode="Markdown",
        )
    except ValueError as e:
        await callback.message.edit_text(  # type: ignore[union-attr]
            f"❌ {e}",
            parse_mode="Markdown",
        )
