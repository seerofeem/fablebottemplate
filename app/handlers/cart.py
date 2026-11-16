from __future__ import annotations

from contextlib import suppress

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.cart import UnknownProductError, change_quantity, clear_cart, get_cart, remove_item
from app.config import ClientConfig
from app.handlers.common import HasMessage, payload
from app.i18n import Translator
from app.keyboards import cart_keyboard
from app.texts import cart_text

router = Router(name="cart")
router.callback_query.filter(HasMessage())


async def render_cart(
    session: AsyncSession, config: ClientConfig, translator: Translator, lang: str, user_id: int
) -> tuple[str, InlineKeyboardMarkup]:
    cart = await get_cart(session, config, user_id)
    return (
        cart_text(translator, lang, cart, config.shop.currency),
        cart_keyboard(cart, translator, lang),
    )


async def refresh_cart(
    msg: Message,
    session: AsyncSession,
    config: ClientConfig,
    translator: Translator,
    lang: str,
    user_id: int,
) -> None:
    text, keyboard = await render_cart(session, config, translator, lang, user_id)
    with suppress(TelegramBadRequest):
        await msg.edit_text(text, reply_markup=keyboard)


@router.message(Command("cart"))
async def cart_command(
    message: Message,
    session: AsyncSession,
    config: ClientConfig,
    translator: Translator,
    lang: str,
    user_id: int,
) -> None:
    text, keyboard = await render_cart(session, config, translator, lang, user_id)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data == "cart")
async def show_cart(
    callback: CallbackQuery,
    msg: Message,
    session: AsyncSession,
    config: ClientConfig,
    translator: Translator,
    lang: str,
    user_id: int,
) -> None:
    await callback.answer()
    text, keyboard = await render_cart(session, config, translator, lang, user_id)
    await msg.answer(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith(("inc:", "dec:")))
async def change_item(
    callback: CallbackQuery,
    msg: Message,
    session: AsyncSession,
    config: ClientConfig,
    translator: Translator,
    lang: str,
    user_id: int,
) -> None:
    delta = 1 if (callback.data or "").startswith("inc:") else -1
    try:
        await change_quantity(session, config, user_id, payload(callback), delta)
    except UnknownProductError:
        await callback.answer(translator.plain(lang, "unknown_product"), show_alert=True)
    else:
        await callback.answer()
    await refresh_cart(msg, session, config, translator, lang, user_id)


@router.callback_query(F.data.startswith("del:"))
async def delete_item(
    callback: CallbackQuery,
    msg: Message,
    session: AsyncSession,
    config: ClientConfig,
    translator: Translator,
    lang: str,
    user_id: int,
) -> None:
    await remove_item(session, user_id, payload(callback))
    await callback.answer()
    await refresh_cart(msg, session, config, translator, lang, user_id)


@router.callback_query(F.data == "clear")
async def clear(
    callback: CallbackQuery,
    msg: Message,
    session: AsyncSession,
    config: ClientConfig,
    translator: Translator,
    lang: str,
    user_id: int,
) -> None:
    await clear_cart(session, user_id)
    await callback.answer()
    await refresh_cart(msg, session, config, translator, lang, user_id)
