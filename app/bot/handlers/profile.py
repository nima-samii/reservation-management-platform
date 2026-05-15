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
from app.bot.keyboards.main_menu import MainMenuButton, get_main_menu
from app.bot.states.reservation import ProfileSG
from app.core.logging import get_logger
from app.db.models.user import Gender, User
from app.services.country import CountryService
from app.services.user import UserService

logger = get_logger(__name__)
router = Router(name="profile")

GENDER_LABELS = {
    Gender.MALE: "👨 Male",
    Gender.FEMALE: "👩 Female",
    Gender.NOT_SAY: "🤐 Prefer not to say",
}


def _profile_edit_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Edit Name", callback_data="profile:edit_name")],
            [InlineKeyboardButton(text="⚧ Edit Gender", callback_data="profile:edit_gender")],
            [InlineKeyboardButton(text="🌍 Edit Country", callback_data="profile:edit_country")],
            [InlineKeyboardButton(text="❌ Close", callback_data="profile:close")],
        ]
    )


def _gender_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=GENDER_LABELS[Gender.MALE], callback_data="profile_gender:male"),
                InlineKeyboardButton(text=GENDER_LABELS[Gender.FEMALE], callback_data="profile_gender:female"),
            ],
            [
                InlineKeyboardButton(text=GENDER_LABELS[Gender.NOT_SAY], callback_data="profile_gender:not_say"),
                InlineKeyboardButton(text="⬅️ Back", callback_data="profile:back"),
            ],
        ]
    )


@router.message(F.text == MainMenuButton.EDIT_PROFILE)
async def show_profile(message: Message, db_user: User | None, session: AsyncSession) -> None:
    if not db_user:
        await message.answer("Please register first with /start")
        return

    country_name = "Not set"
    if db_user.country_rel:
        flag = db_user.country_rel.flag_emoji or ""
        country_name = f"{flag} {db_user.country_rel.name}".strip()

    gender_display = "Not set"
    if db_user.gender:
        gender_display = GENDER_LABELS.get(db_user.gender, db_user.gender)  # type: ignore[arg-type]

    await message.answer(
        f"👤 *Your Profile*\n\n"
        f"🔑 ID: `{db_user.public_user_code}`\n"
        f"📛 Name: {db_user.full_name}\n"
        f"⚧ Gender: {gender_display}\n"
        f"🌍 Country: {country_name}\n\n"
        "What would you like to edit?",
        reply_markup=_profile_edit_keyboard(),
        parse_mode="Markdown",
    )
    await message.answer("📌 Main Menu", reply_markup=get_main_menu())


@router.callback_query(F.data == "profile:close")
async def close_profile(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await callback.message.delete()  # type: ignore[union-attr]


@router.callback_query(F.data == "profile:back")
async def profile_back(callback: CallbackQuery, state: FSMContext, db_user: User | None, session: AsyncSession) -> None:
    await callback.answer()
    await state.clear()
    country_name = "Not set"
    if db_user and db_user.country_rel:
        flag = db_user.country_rel.flag_emoji or ""
        country_name = f"{flag} {db_user.country_rel.name}".strip()

    gender_display = "Not set"
    if db_user and db_user.gender:
        gender_display = GENDER_LABELS.get(db_user.gender, db_user.gender)  # type: ignore[arg-type]

    await callback.message.edit_text(  # type: ignore[union-attr]
        f"👤 *Your Profile*\n\n"
        f"🔑 ID: `{db_user.public_user_code if db_user else 'N/A'}`\n"  # type: ignore[union-attr]
        f"📛 Name: {db_user.full_name if db_user else 'N/A'}\n"  # type: ignore[union-attr]
        f"⚧ Gender: {gender_display}\n"
        f"🌍 Country: {country_name}\n\n"
        "What would you like to edit?",
        reply_markup=_profile_edit_keyboard(),
        parse_mode="Markdown",
    )


# ── Edit Name ─────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "profile:edit_name")
async def edit_name_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await callback.message.edit_text(  # type: ignore[union-attr]
        "✏️ *Edit Name*\n\nPlease enter your new full name:",
        parse_mode="Markdown",
    )
    await state.set_state(ProfileSG.edit_name)


@router.message(ProfileSG.edit_name)
async def receive_new_name(message: Message, state: FSMContext, session: AsyncSession, db_user: User | None) -> None:
    name = message.text.strip() if message.text else ""
    if not name or len(name) < 2:
        await message.answer("⚠️ Name must be at least 2 characters. Try again:")
        return
    if len(name) > 100:
        await message.answer("⚠️ Name too long (max 100 chars). Try again:")
        return

    if not db_user:
        return

    svc = UserService(session)
    await svc.update_profile(db_user.telegram_id, full_name=name)
    await state.clear()
    await message.answer(
        f"✅ Name updated to: *{name}*",
        reply_markup=get_main_menu(),
        parse_mode="Markdown",
    )


# ── Edit Gender ───────────────────────────────────────────────────────────────

@router.callback_query(F.data == "profile:edit_gender")
async def edit_gender_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await callback.message.edit_text(  # type: ignore[union-attr]
        "⚧ *Edit Gender*\n\nSelect your gender:",
        reply_markup=_gender_keyboard(),
        parse_mode="Markdown",
    )
    await state.set_state(ProfileSG.choose_gender)


@router.callback_query(ProfileSG.choose_gender, F.data.startswith("profile_gender:"))
async def receive_new_gender(callback: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User | None) -> None:
    await callback.answer()
    gender = callback.data.split(":", 1)[1]  # type: ignore[union-attr]

    if not db_user:
        return

    svc = UserService(session)
    await svc.update_profile(db_user.telegram_id, gender=gender)
    await state.clear()
    label = GENDER_LABELS.get(gender, gender)  # type: ignore[arg-type]
    await callback.message.edit_text(  # type: ignore[union-attr]
        f"✅ Gender updated to: {label}",
        parse_mode="Markdown",
    )


# ── Edit Country ──────────────────────────────────────────────────────────────

@router.callback_query(F.data == "profile:edit_country")
async def edit_country_prompt(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await callback.answer()
    country_svc = CountryService(session)
    countries = await country_svc.get_all()
    await callback.message.edit_text(  # type: ignore[union-attr]
        "🌍 *Edit Country*\n\nSelect your country:",
        reply_markup=build_country_keyboard(countries[:16]),
        parse_mode="Markdown",
    )
    await state.set_state(ProfileSG.choose_country)


@router.callback_query(ProfileSG.choose_country, F.data == "country:search")
async def profile_country_search_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await callback.message.edit_text("🔍 Type your country name:")  # type: ignore[union-attr]
    await state.set_state(ProfileSG.search_country)


@router.message(ProfileSG.search_country)
async def profile_country_search_result(message: Message, state: FSMContext, session: AsyncSession) -> None:
    query = message.text.strip() if message.text else ""
    country_svc = CountryService(session)
    countries = await country_svc.search(query)

    if not countries:
        await message.answer("❌ No countries found. Please try again:")
        return

    from app.bot.keyboards.inline.countries import build_country_search_result_keyboard
    await message.answer(
        f"🌍 Results for *{query}*:",
        reply_markup=build_country_search_result_keyboard(countries),
        parse_mode="Markdown",
    )
    await state.set_state(ProfileSG.choose_country)


@router.callback_query(ProfileSG.choose_country, F.data.startswith("country:"))
async def profile_choose_country(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    db_user: User | None,
) -> None:
    code = callback.data.split(":", 1)[1]  # type: ignore[union-attr]
    if code in ("search", "cancel"):
        if code == "cancel":
            await callback.answer()
            await state.clear()
        return

    await callback.answer()
    country_svc = CountryService(session)
    country = await country_svc.get_by_code(code)

    if not country or not db_user:
        await callback.answer("Country not found.", show_alert=True)
        return

    svc = UserService(session)
    await svc.update_profile(db_user.telegram_id, country_id=str(country.id))
    await state.clear()

    flag = country.flag_emoji or ""
    await callback.message.edit_text(  # type: ignore[union-attr]
        f"✅ Country updated to: {flag} {country.name}",
        parse_mode="Markdown",
    )
