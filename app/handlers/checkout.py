from __future__ import annotations

import re

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove
from sqlalchemy.ext.asyncio import AsyncSession

from app.cart import get_cart
from app.config import ClientConfig
from app.handlers.common import HasMessage, payload
from app.i18n import Translator, join_lines
from app.keyboards import (
    cancel_keyboard,
    cart_keyboard,
    confirm_keyboard,
    delivery_keyboard,
    phone_keyboard,
)
from app.orders import (
    CheckoutData,
    DealCreator,
    EmptyCartError,
    UnknownDeliveryError,
    place_order,
)
from app.texts import cart_text, confirmation_text

NAME_LENGTH = (2, 64)
ADDRESS_LENGTH = (5, 300)
PHONE_DIGITS = (10, 15)

router = Router(name="checkout")
router.callback_query.filter(HasMessage())


class Checkout(StatesGroup):
    name = State()
    phone = State()
    delivery = State()
    address = State()
    confirm = State()


def normalize_phone(raw: str) -> str | None:
    if re.search(r"[^\d\s()+\-]", raw):
        return None
    digits = re.sub(r"\D", "", raw)
    if not PHONE_DIGITS[0] <= len(digits) <= PHONE_DIGITS[1]:
        return None
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    return f"+{digits}"


def clean_text(raw: str | None, limits: tuple[int, int]) -> str | None:
    text = " ".join((raw or "").split())
    if text.startswith("/") or not limits[0] <= len(text) <= limits[1]:
        return None
    return text


async def show_confirmation(
    msg: Message,
    state: FSMContext,
    session: AsyncSession,
    config: ClientConfig,
    translator: Translator,
    lang: str,
    user_id: int,
) -> None:
    data = await state.get_data()
    option = config.delivery_option(str(data.get("delivery_id", "")))
    cart = await get_cart(session, config, user_id)
    if option is None or cart.is_empty:
        await state.clear()
        await msg.answer(
            cart_text(translator, lang, cart, config.shop.currency),
            reply_markup=cart_keyboard(cart, translator, lang),
        )
        return
    await state.set_state(Checkout.confirm)
    await msg.answer(
        confirmation_text(
            translator,
            lang,
            config,
            cart,
            str(data.get("name", "")),
            str(data.get("phone", "")),
            option,
            str(data.get("address", "")) if option.needs_address else "",
        ),
        reply_markup=confirm_keyboard(translator, lang),
    )


async def accept_phone(
    message: Message,
    state: FSMContext,
    config: ClientConfig,
    translator: Translator,
    lang: str,
    phone: str,
) -> None:
    await state.update_data(phone=phone)
    await state.set_state(Checkout.delivery)
    await message.answer(
        translator.t(lang, "phone_saved", phone=phone), reply_markup=ReplyKeyboardRemove()
    )
    await message.answer(
        translator.t(lang, "ask_delivery"),
        reply_markup=delivery_keyboard(config, translator, lang),
    )


@router.callback_query(F.data == "checkout")
async def begin(
    callback: CallbackQuery,
    msg: Message,
    state: FSMContext,
    session: AsyncSession,
    config: ClientConfig,
    translator: Translator,
    lang: str,
    user_id: int,
) -> None:
    cart = await get_cart(session, config, user_id)
    if cart.is_empty:
        await callback.answer(translator.plain(lang, "cart_empty"), show_alert=True)
        return
    await callback.answer()
    await state.clear()
    await state.set_state(Checkout.name)
    await msg.answer(translator.t(lang, "ask_name"), reply_markup=cancel_keyboard(translator, lang))


@router.callback_query(F.data == "cancel")
async def cancel(
    callback: CallbackQuery, msg: Message, state: FSMContext, translator: Translator, lang: str
) -> None:
    await state.clear()
    await callback.answer()
    await msg.answer(translator.t(lang, "checkout_cancelled"), reply_markup=ReplyKeyboardRemove())


@router.message(Checkout.name)
async def name_entered(
    message: Message, state: FSMContext, translator: Translator, lang: str
) -> None:
    name = clean_text(message.text, NAME_LENGTH)
    if name is None:
        await message.answer(translator.t(lang, "invalid_name"))
        return
    await state.update_data(name=name)
    await state.set_state(Checkout.phone)
    await message.answer(
        translator.t(lang, "ask_phone"), reply_markup=phone_keyboard(translator, lang)
    )


@router.message(Checkout.phone)
async def phone_entered(
    message: Message,
    state: FSMContext,
    config: ClientConfig,
    translator: Translator,
    lang: str,
    user_id: int,
) -> None:
    raw = message.text or ""
    if message.contact is not None and message.contact.user_id in (None, user_id):
        raw = message.contact.phone_number
    phone = normalize_phone(raw)
    if phone is None:
        await message.answer(
            translator.t(lang, "invalid_phone"), reply_markup=phone_keyboard(translator, lang)
        )
        return
    await accept_phone(message, state, config, translator, lang, phone)


@router.callback_query(Checkout.delivery, F.data.startswith("dlv:"))
async def delivery_chosen(
    callback: CallbackQuery,
    msg: Message,
    state: FSMContext,
    session: AsyncSession,
    config: ClientConfig,
    translator: Translator,
    lang: str,
    user_id: int,
) -> None:
    option = config.delivery_option(payload(callback))
    await callback.answer()
    if option is None:
        await msg.answer(
            translator.t(lang, "ask_delivery"),
            reply_markup=delivery_keyboard(config, translator, lang),
        )
        return
    await state.update_data(delivery_id=option.id)
    if option.needs_address:
        await state.set_state(Checkout.address)
        await msg.answer(
            translator.t(lang, "ask_address"), reply_markup=cancel_keyboard(translator, lang)
        )
        return
    await show_confirmation(msg, state, session, config, translator, lang, user_id)


@router.message(Checkout.address)
async def address_entered(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    config: ClientConfig,
    translator: Translator,
    lang: str,
    user_id: int,
) -> None:
    address = clean_text(message.text, ADDRESS_LENGTH)
    if address is None:
        await message.answer(translator.t(lang, "invalid_address"))
        return
    await state.update_data(address=address)
    await show_confirmation(message, state, session, config, translator, lang, user_id)


@router.callback_query(Checkout.confirm, F.data == "confirm")
async def confirm(
    callback: CallbackQuery,
    msg: Message,
    state: FSMContext,
    session: AsyncSession,
    config: ClientConfig,
    translator: Translator,
    lang: str,
    user_id: int,
    bot: Bot,
    crm: DealCreator | None,
) -> None:
    data = await state.get_data()
    await state.clear()
    await callback.answer()
    checkout = CheckoutData(
        name=str(data.get("name", "")),
        phone=str(data.get("phone", "")),
        delivery_id=str(data.get("delivery_id", "")),
        address=str(data.get("address", "")),
    )
    try:
        order = await place_order(
            session, config, translator, user_id, lang, checkout, crm, bot.send_message
        )
    except (EmptyCartError, UnknownDeliveryError):
        await msg.answer(translator.t(lang, "checkout_expired"))
        return
    parts = [translator.t(lang, "order_accepted", id=order.id)]
    if not config.is_open():
        parts.append(translator.t(lang, "closed_note"))
    await msg.answer(join_lines(parts))


@router.callback_query(StateFilter(None), F.data.startswith("dlv:") | (F.data == "confirm"))
async def expired(callback: CallbackQuery, msg: Message, translator: Translator, lang: str) -> None:
    await callback.answer()
    await msg.answer(translator.t(lang, "checkout_expired"))
