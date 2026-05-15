from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.models.country import Country

COUNTRIES_PAGE_SIZE = 8


def build_country_keyboard(
    countries: list[Country],
    show_search_button: bool = True,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    for country in countries:
        flag = country.flag_emoji or ""
        label = f"{flag} {country.name}".strip()
        builder.button(
            text=label,
            callback_data=f"country:{country.code}",
        )

    builder.adjust(2)

    if show_search_button:
        builder.row(
            *[
                __import__("aiogram").types.InlineKeyboardButton(
                    text="🔍 Search country",
                    callback_data="country:search",
                )
            ]
        )

    builder.row(
        *[
            __import__("aiogram").types.InlineKeyboardButton(
                text="❌ Cancel",
                callback_data="country:cancel",
            )
        ]
    )

    return builder.as_markup()


def build_country_search_result_keyboard(
    countries: list[Country],
    context: str = "register",
) -> InlineKeyboardMarkup:
    """context: 'register' | 'profile'"""
    builder = InlineKeyboardBuilder()

    for country in countries:
        flag = country.flag_emoji or ""
        label = f"{flag} {country.name}".strip()
        builder.button(
            text=label,
            callback_data=f"country:{country.code}",
        )

    builder.adjust(2)
    builder.row(
        *[
            __import__("aiogram").types.InlineKeyboardButton(
                text="🔍 Search again",
                callback_data="country:search",
            ),
            __import__("aiogram").types.InlineKeyboardButton(
                text="❌ Cancel",
                callback_data="country:cancel",
            ),
        ]
    )
    return builder.as_markup()
