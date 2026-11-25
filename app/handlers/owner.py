from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import ClientConfig
from app.handlers.common import OwnerChat, Routes
from app.i18n import Translator
from app.models import STATUSES
from app.orders import recent_orders, set_status
from app.texts import orders_list_text, status_label

logger = logging.getLogger(__name__)

router = Routes("owner", message_filters=(OwnerChat(),))


def parse_status_args(args: str | None) -> tuple[int, str] | None:
    parts = (args or "").split()
    if len(parts) != 2 or not parts[0].lstrip("#№").isdigit():
        return None
    status = parts[1].lower()
    if status not in STATUSES:
        return None
    return int(parts[0].lstrip("#№")), status


@router.message(Command("orders"))
async def orders(
    message: Message, session: AsyncSession, config: ClientConfig, translator: Translator
) -> None:
    lang = config.default_language
    await message.answer(
        orders_list_text(translator, lang, await recent_orders(session), config.shop.timezone)
    )


@router.message(Command("status"))
async def status(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
    config: ClientConfig,
    translator: Translator,
    bot: Bot,
) -> None:
    lang = config.default_language
    parsed = parse_status_args(command.args)
    if parsed is None:
        await message.answer(translator.t(lang, "status_usage"))
        return
    order_id, new_status = parsed
    order = await set_status(session, order_id, new_status)
    if order is None:
        await message.answer(translator.t(lang, "status_not_found", id=order_id))
        return
    await message.answer(
        translator.t(
            lang, "status_updated", id=order.id, status=status_label(translator, lang, new_status)
        )
    )
    try:
        await bot.send_message(
            order.user_id,
            translator.t(
                order.lang,
                "customer_status",
                id=order.id,
                status=status_label(translator, order.lang, new_status),
            ),
        )
    except TelegramAPIError as exc:
        logger.warning("Status message to customer of order %s failed: %s", order.id, exc)
