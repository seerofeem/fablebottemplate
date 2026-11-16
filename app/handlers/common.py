from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.filters import Filter
from aiogram.types import CallbackQuery, Message, TelegramObject
from aiogram.types import User as TelegramUser
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import ClientConfig
from app.db import SessionFactory
from app.models import User


class HasMessage(Filter):
    async def __call__(self, callback: CallbackQuery) -> bool | dict[str, Any]:
        if isinstance(callback.message, Message):
            return {"msg": callback.message}
        return False


class OwnerChat(Filter):
    async def __call__(self, message: Message, config: ClientConfig) -> bool:
        return message.chat.id == config.owner_chat_id


class ContextMiddleware(BaseMiddleware):
    def __init__(self, session_factory: SessionFactory, config: ClientConfig) -> None:
        self._session_factory = session_factory
        self._config = config

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        telegram_user = data.get("event_from_user")
        async with self._session_factory() as session:
            lang = self._config.default_language
            user_id = 0
            if isinstance(telegram_user, TelegramUser):
                user_id = telegram_user.id
                user = await session.get(User, user_id)
                if user is not None and user.lang in self._config.shop.languages:
                    lang = user.lang
            data["session"] = session
            data["user_id"] = user_id
            data["lang"] = lang
            return await handler(event, data)


def payload(callback: CallbackQuery) -> str:
    return (callback.data or "").partition(":")[2]


async def save_language(session: AsyncSession, user_id: int, lang: str) -> None:
    user = await session.get(User, user_id)
    if user is None:
        session.add(User(id=user_id, lang=lang))
    else:
        user.lang = lang
    await session.commit()
