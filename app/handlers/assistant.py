from __future__ import annotations

from aiogram import F
from aiogram.enums import ChatAction
from aiogram.filters import StateFilter
from aiogram.types import Message

from app.assistant import Answerer, DailyLimit
from app.config import ClientConfig
from app.handlers.common import Routes
from app.i18n import Translator, escape
from app.keyboards import menu_keyboard

router = Routes("assistant")


@router.message(StateFilter(None), F.text, ~F.text.startswith("/"))
async def ask(
    message: Message,
    config: ClientConfig,
    translator: Translator,
    lang: str,
    user_id: int,
    assistant: Answerer,
    assistant_limit: DailyLimit,
) -> None:
    if message.chat.id == config.owner_chat_id:
        return
    keyboard = menu_keyboard(config, translator, lang)
    if not assistant_limit.take(user_id):
        await message.answer(translator.t(lang, "assistant_limit"), reply_markup=keyboard)
        return
    if message.bot is not None:
        await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    reply = await assistant.answer(message.text or "", lang)
    if reply is None:
        await message.answer(translator.t(lang, "assistant_unavailable"), reply_markup=keyboard)
        return
    await message.answer(escape(reply), reply_markup=keyboard)
