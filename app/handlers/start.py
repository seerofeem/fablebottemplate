from __future__ import annotations

from aiogram import F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import ClientConfig, pick
from app.handlers.common import HasMessage, Routes, payload, save_language
from app.i18n import Translator
from app.keyboards import language_keyboard, menu_keyboard

router = Routes("start", callback_filters=(HasMessage(),))


async def send_menu(msg: Message, config: ClientConfig, translator: Translator, lang: str) -> None:
    await msg.answer(
        translator.t(
            lang, "welcome", shop=config.shop.name, welcome=pick(config.shop.welcome, lang)
        ),
        reply_markup=menu_keyboard(config, translator, lang),
    )


@router.message(CommandStart())
async def start(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    config: ClientConfig,
    translator: Translator,
    lang: str,
    user_id: int,
) -> None:
    if await state.get_state() is not None:
        await state.clear()
        await message.answer(
            translator.t(lang, "checkout_cancelled"), reply_markup=ReplyKeyboardRemove()
        )
    if len(config.shop.languages) > 1:
        await message.answer(
            translator.t(lang, "choose_language"), reply_markup=language_keyboard(config)
        )
        return
    await save_language(session, user_id, lang)
    await send_menu(message, config, translator, lang)


@router.callback_query(F.data.startswith("lang:"))
async def choose_language(
    callback: CallbackQuery,
    msg: Message,
    session: AsyncSession,
    config: ClientConfig,
    translator: Translator,
    user_id: int,
) -> None:
    code = payload(callback)
    if code not in config.shop.languages:
        code = config.default_language
    await save_language(session, user_id, code)
    await callback.answer()
    await send_menu(msg, config, translator, code)


@router.callback_query(F.data == "language")
async def change_language(
    callback: CallbackQuery, msg: Message, config: ClientConfig, translator: Translator, lang: str
) -> None:
    await callback.answer()
    await msg.answer(translator.t(lang, "choose_language"), reply_markup=language_keyboard(config))


@router.callback_query(F.data == "menu")
async def menu(
    callback: CallbackQuery, msg: Message, config: ClientConfig, translator: Translator, lang: str
) -> None:
    await callback.answer()
    await send_menu(msg, config, translator, lang)


@router.callback_query(F.data == "noop")
async def noop(callback: CallbackQuery) -> None:
    await callback.answer()
