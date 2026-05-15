from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.inline.countries import build_country_keyboard
from app.bot.keyboards.main_menu import get_main_menu
from app.bot.states.registration import RegistrationSG
from app.core.exceptions import AlreadyExistsError
from app.core.logging import get_logger
from app.db.models.user import Gender
from app.services.country import CountryService
from app.services.user import UserService

logger = get_logger(__name__)
router = Router(name="registration")

GENDER_LABELS = {
    Gender.MALE: "👨 Male",
    Gender.FEMALE: "👩 Female",
    Gender.NOT_SAY: "🤐 Prefer not to say",
}


def _gender_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=GENDER_LABELS[Gender.MALE], callback_data="gender:male"),
                InlineKeyboardButton(text=GENDER_LABELS[Gender.FEMALE], callback_data="gender:female"),
            ],
            [
                InlineKeyboardButton(text=GENDER_LABELS[Gender.NOT_SAY], callback_data="gender:not_say"),
            ],
        ]
    )


# ── Name confirmation ─────────────────────────────────────────────────────────

@router.callback_query(RegistrationSG.confirm_name, F.data == "reg:confirm_name")
async def confirm_name(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    data = await state.get_data()
    await state.update_data(full_name=data["detected_name"])
    await callback.message.edit_text(  # type: ignore[union-attr]
        "✅ Name confirmed!\n\n"
        "Please select your gender:",
        reply_markup=_gender_keyboard(),
    )
    await state.set_state(RegistrationSG.choose_gender)


@router.callback_query(RegistrationSG.confirm_name, F.data == "reg:edit_name")
async def ask_edit_name(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await callback.message.edit_text(  # type: ignore[union-attr]
        "✏️ Please type your full name:"
    )
    await state.set_state(RegistrationSG.edit_name)


@router.message(RegistrationSG.edit_name)
async def receive_edited_name(message: Message, state: FSMContext) -> None:
    name = message.text.strip() if message.text else ""
    if not name or len(name) < 2:
        await message.answer("⚠️ Name must be at least 2 characters. Please try again:")
        return
    if len(name) > 100:
        await message.answer("⚠️ Name is too long (max 100 characters). Please try again:")
        return

    await state.update_data(full_name=name)
    await message.answer(
        f"✅ Name set to: *{name}*\n\nPlease select your gender:",
        reply_markup=_gender_keyboard(),
        parse_mode="Markdown",
    )
    await state.set_state(RegistrationSG.choose_gender)


# ── Gender ────────────────────────────────────────────────────────────────────

@router.callback_query(RegistrationSG.choose_gender, F.data.startswith("gender:"))
async def choose_gender(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await callback.answer()
    gender_value = callback.data.split(":", 1)[1]  # type: ignore[union-attr]

    await state.update_data(gender=gender_value)

    country_svc = CountryService(session)
    countries = await country_svc.get_all()

    await callback.message.edit_text(  # type: ignore[union-attr]
        "🌍 Please select your country:\n\n"
        "Use *Search* to find your country quickly.",
        reply_markup=build_country_keyboard(countries[:16]),
        parse_mode="Markdown",
    )
    await state.set_state(RegistrationSG.choose_country)


# ── Country selection ─────────────────────────────────────────────────────────

@router.callback_query(RegistrationSG.choose_country, F.data == "country:search")
async def ask_country_search(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await callback.message.edit_text(  # type: ignore[union-attr]
        "🔍 Type the name of your country:"
    )
    await state.set_state(RegistrationSG.search_country)


@router.message(RegistrationSG.search_country)
async def country_search_result(message: Message, state: FSMContext, session: AsyncSession) -> None:
    query = message.text.strip() if message.text else ""
    country_svc = CountryService(session)
    countries = await country_svc.search(query)

    if not countries:
        await message.answer(
            "❌ No countries found. Please try again:",
        )
        return

    from app.bot.keyboards.inline.countries import build_country_search_result_keyboard
    await message.answer(
        f"🌍 Results for *{query}*:",
        reply_markup=build_country_search_result_keyboard(countries),
        parse_mode="Markdown",
    )
    await state.set_state(RegistrationSG.choose_country)


@router.callback_query(RegistrationSG.choose_country, F.data.startswith("country:"))
async def choose_country(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    code = callback.data.split(":", 1)[1]  # type: ignore[union-attr]
    if code in ("search", "cancel"):
        if code == "cancel":
            await callback.answer("Cancelled.")
            await state.clear()
        return

    await callback.answer()

    country_svc = CountryService(session)
    country = await country_svc.get_by_code(code)
    if not country:
        await callback.answer("Country not found. Please try again.", show_alert=True)
        return

    await state.update_data(country_id=str(country.id))

    data = await state.get_data()
    full_name: str = data.get("full_name", "")
    gender: str | None = data.get("gender")

    tg_user = callback.from_user
    username = tg_user.username if tg_user else None

    try:
        user_svc = UserService(session)
        user = await user_svc.register(
            telegram_id=tg_user.id,  # type: ignore[union-attr]
            full_name=full_name,
            username=username,
            gender=gender,
            country_id=data.get("country_id"),
        )
    except AlreadyExistsError:
        user_svc = UserService(session)
        user = await user_svc.get_or_none(tg_user.id)  # type: ignore[union-attr]

    await state.clear()

    flag = country.flag_emoji or ""
    await callback.message.edit_text(  # type: ignore[union-attr]
        f"🎉 *Registration complete!*\n\n"
        f"👤 Name: {full_name}\n"
        f"🌍 Country: {flag} {country.name}\n"
        f"🔑 Your ID: `{user.public_user_code if user else 'N/A'}`\n\n"  # type: ignore[union-attr]
        "You're all set! Use the menu below to get started.",
        parse_mode="Markdown",
    )
    await callback.message.answer(  # type: ignore[union-attr]
        "📌 Main Menu",
        reply_markup=get_main_menu(),
    )
