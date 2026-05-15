from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.filters.registered import IsNotRegisteredFilter, IsRegisteredFilter
from app.bot.keyboards.main_menu import get_main_menu
from app.bot.states.registration import RegistrationSG
from app.db.models.user import User

router = Router(name="start")


@router.message(CommandStart(), IsRegisteredFilter())
async def start_registered(message: Message, db_user: User, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        f"👋 Welcome back, *{db_user.full_name}*!\n\n"
        f"Your ID: `{db_user.public_user_code}`\n\n"
        "What would you like to do today?",
        reply_markup=get_main_menu(),
        parse_mode="Markdown",
    )


@router.message(CommandStart(), IsNotRegisteredFilter())
async def start_unregistered(message: Message, state: FSMContext) -> None:
    await state.clear()

    first = message.from_user.first_name or ""
    last = message.from_user.last_name or ""
    detected_name = " ".join(filter(None, [first, last])).strip() or "Unknown"

    await state.update_data(detected_name=detected_name)

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"✅ Confirm: {detected_name}",
                    callback_data="reg:confirm_name",
                )
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Edit name",
                    callback_data="reg:edit_name",
                )
            ],
        ]
    )

    await message.answer(
        "👋 Welcome to *19-Step English Learning Bot*!\n\n"
        f"We detected your Telegram name as:\n*{detected_name}*\n\n"
        "Please confirm or edit it:",
        reply_markup=kb,
        parse_mode="Markdown",
    )
    await state.set_state(RegistrationSG.confirm_name)
