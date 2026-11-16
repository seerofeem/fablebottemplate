from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.cart import UnknownProductError, change_quantity
from app.config import ClientConfig, Product, pick
from app.handlers.common import HasMessage, payload
from app.i18n import Translator
from app.keyboards import categories_keyboard, category_footer_keyboard, product_keyboard
from app.texts import format_money

logger = logging.getLogger(__name__)

router = Router(name="catalog")
router.callback_query.filter(HasMessage())


async def send_categories(
    msg: Message, config: ClientConfig, translator: Translator, lang: str
) -> None:
    await msg.answer(
        translator.t(lang, "choose_category"),
        reply_markup=categories_keyboard(config, translator, lang),
    )


async def send_product(
    msg: Message, product: Product, config: ClientConfig, translator: Translator, lang: str
) -> None:
    currency = config.shop.currency
    caption = translator.t(
        lang,
        "product_caption",
        name=pick(product.name, lang),
        price=format_money(product.price, currency),
        description=pick(product.description, lang),
    )
    keyboard = product_keyboard(product, translator, lang, currency)
    if product.photo_url is not None:
        try:
            await msg.answer_photo(str(product.photo_url), caption=caption, reply_markup=keyboard)
            return
        except TelegramAPIError as exc:
            logger.warning("Photo for product %s failed: %s", product.id, exc)
    await msg.answer(caption, reply_markup=keyboard)


@router.message(Command("catalog"))
async def catalog_command(
    message: Message, config: ClientConfig, translator: Translator, lang: str
) -> None:
    await send_categories(message, config, translator, lang)


@router.callback_query(F.data == "catalog")
async def catalog(
    callback: CallbackQuery, msg: Message, config: ClientConfig, translator: Translator, lang: str
) -> None:
    await callback.answer()
    await send_categories(msg, config, translator, lang)


@router.callback_query(F.data.startswith("cat:"))
async def category(
    callback: CallbackQuery, msg: Message, config: ClientConfig, translator: Translator, lang: str
) -> None:
    await callback.answer()
    selected = config.category(payload(callback))
    if selected is None:
        await send_categories(msg, config, translator, lang)
        return
    for product in selected.products:
        await send_product(msg, product, config, translator, lang)
    await msg.answer(
        translator.t(lang, "category_footer", name=pick(selected.name, lang)),
        reply_markup=category_footer_keyboard(selected, translator, lang),
    )


@router.callback_query(F.data.startswith("add:"))
async def add_to_cart(
    callback: CallbackQuery,
    session: AsyncSession,
    config: ClientConfig,
    translator: Translator,
    lang: str,
    user_id: int,
) -> None:
    product_id = payload(callback)
    try:
        quantity = await change_quantity(session, config, user_id, product_id, 1)
    except UnknownProductError:
        await callback.answer(translator.plain(lang, "unknown_product"), show_alert=True)
        return
    product = config.product(product_id)
    name = pick(product.name, lang) if product is not None else product_id
    await callback.answer(translator.plain(lang, "added_to_cart", name=name, quantity=quantity))
