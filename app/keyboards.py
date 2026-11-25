from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from app.cart import Cart
from app.config import Category, ClientConfig, Product, pick
from app.i18n import Translator
from app.texts import delivery_label, format_money

LANGUAGE_NAMES = {"ru": "🇷🇺 Русский", "kk": "🇰🇿 Қазақша"}
BUTTON_TEXT_LIMIT = 28


def button(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def markup(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def shorten(text: str) -> str:
    return text if len(text) <= BUTTON_TEXT_LIMIT else text[: BUTTON_TEXT_LIMIT - 1] + "…"


def language_keyboard(config: ClientConfig) -> InlineKeyboardMarkup:
    return markup(
        [[button(LANGUAGE_NAMES[code], f"lang:{code}") for code in config.shop.languages]]
    )


def menu_keyboard(config: ClientConfig, translator: Translator, lang: str) -> InlineKeyboardMarkup:
    rows = [
        [
            button(translator.plain(lang, "btn_catalog"), "catalog"),
            button(translator.plain(lang, "btn_cart"), "cart"),
        ]
    ]
    if len(config.shop.languages) > 1:
        rows.append([button(translator.plain(lang, "btn_language"), "language")])
    return markup(rows)


def categories_keyboard(
    config: ClientConfig, translator: Translator, lang: str
) -> InlineKeyboardMarkup:
    rows = [
        [button(pick(category.name, lang), f"cat:{category.id}")] for category in config.categories
    ]
    rows.append(
        [
            button(translator.plain(lang, "btn_cart"), "cart"),
            button(translator.plain(lang, "btn_menu"), "menu"),
        ]
    )
    return markup(rows)


def product_keyboard(
    product: Product, translator: Translator, lang: str, currency: str
) -> InlineKeyboardMarkup:
    text = translator.plain(lang, "btn_add", price=format_money(product.price, currency))
    return markup([[button(text, f"add:{product.id}")]])


def category_footer_keyboard(
    category: Category, translator: Translator, lang: str
) -> InlineKeyboardMarkup:
    return markup(
        [
            [
                button(translator.plain(lang, "btn_categories"), "catalog"),
                button(translator.plain(lang, "btn_cart"), "cart"),
            ]
        ]
    )


def cart_keyboard(cart: Cart, translator: Translator, lang: str) -> InlineKeyboardMarkup:
    if cart.is_empty:
        return markup([[button(translator.plain(lang, "btn_catalog"), "catalog")]])
    rows = []
    for index, line in enumerate(cart.lines, start=1):
        product_id = line.product.id
        rows.append(
            [
                button(shorten(f"{index}. {pick(line.product.name, lang)}"), "noop"),
                button("➖", f"dec:{product_id}"),
                button(str(line.quantity), "noop"),
                button("➕", f"inc:{product_id}"),
                button("✖️", f"del:{product_id}"),
            ]
        )
    rows.append([button(translator.plain(lang, "btn_checkout"), "checkout")])
    rows.append(
        [
            button(translator.plain(lang, "btn_clear"), "clear"),
            button(translator.plain(lang, "btn_catalog"), "catalog"),
        ]
    )
    return markup(rows)


def phone_keyboard(translator: Translator, lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=translator.plain(lang, "btn_send_phone"), request_contact=True)]
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def cancel_keyboard(translator: Translator, lang: str) -> InlineKeyboardMarkup:
    return markup([[button(translator.plain(lang, "btn_cancel"), "cancel")]])


def delivery_keyboard(
    config: ClientConfig, translator: Translator, lang: str
) -> InlineKeyboardMarkup:
    rows = [
        [button(delivery_label(translator, lang, option, config.shop.currency), f"dlv:{option.id}")]
        for option in config.delivery
    ]
    rows.append([button(translator.plain(lang, "btn_cancel"), "cancel")])
    return markup(rows)


def confirm_keyboard(translator: Translator, lang: str) -> InlineKeyboardMarkup:
    return markup(
        [
            [
                button(translator.plain(lang, "btn_confirm"), "confirm"),
                button(translator.plain(lang, "btn_cancel"), "cancel"),
            ]
        ]
    )
