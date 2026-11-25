from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cart import clear_cart, get_cart
from app.config import ClientConfig, pick
from app.i18n import Translator
from app.models import STATUSES, Order, OrderItem
from app.texts import owner_order_text

logger = logging.getLogger(__name__)

Notifier = Callable[[int, str], Awaitable[object]]


class DealCreator(Protocol):
    async def create_deal(self, order: Order) -> int: ...


class EmptyCartError(Exception):
    pass


class UnknownDeliveryError(Exception):
    pass


class InvalidStatusError(Exception):
    pass


@dataclass(frozen=True)
class CheckoutData:
    name: str
    phone: str
    delivery_id: str
    address: str = ""


async def create_order(
    session: AsyncSession, config: ClientConfig, user_id: int, lang: str, data: CheckoutData
) -> Order:
    option = config.delivery_option(data.delivery_id)
    if option is None:
        raise UnknownDeliveryError(data.delivery_id)
    cart = await get_cart(session, config, user_id)
    if cart.is_empty:
        raise EmptyCartError
    owner_lang = config.default_language
    order = Order(
        user_id=user_id,
        lang=lang,
        customer_name=data.name,
        phone=data.phone,
        delivery_id=option.id,
        delivery_name=pick(option.name, owner_lang),
        delivery_price=option.price,
        address=data.address if option.needs_address else "",
        items_total=cart.total,
        total=cart.total + option.price,
        currency=config.shop.currency,
        items=[
            OrderItem(
                product_id=line.product.id,
                name=pick(line.product.name, owner_lang),
                price=line.product.price,
                quantity=line.quantity,
            )
            for line in cart.lines
        ],
    )
    session.add(order)
    await session.flush()
    await clear_cart(session, user_id)
    return order


async def dispatch_order(
    session: AsyncSession,
    config: ClientConfig,
    translator: Translator,
    order: Order,
    crm: DealCreator | None,
    notify: Notifier,
) -> None:
    crm_failed = False
    if crm is not None:
        try:
            order.bitrix_deal_id = await crm.create_deal(order)
            await session.commit()
        except Exception as exc:
            crm_failed = True
            logger.error("Bitrix24 deal for order %s failed: %s", order.id, exc)
    text = owner_order_text(translator, config.default_language, order, crm is not None, crm_failed)
    try:
        await notify(config.owner_chat_id, text)
    except Exception as exc:
        logger.error("Owner notification for order %s failed: %s", order.id, exc)


async def place_order(
    session: AsyncSession,
    config: ClientConfig,
    translator: Translator,
    user_id: int,
    lang: str,
    data: CheckoutData,
    crm: DealCreator | None,
    notify: Notifier,
) -> Order:
    order = await create_order(session, config, user_id, lang, data)
    await dispatch_order(session, config, translator, order, crm, notify)
    return order


async def recent_orders(session: AsyncSession, limit: int = 10) -> list[Order]:
    rows = await session.scalars(select(Order).order_by(Order.id.desc()).limit(limit))
    return list(rows)


async def set_status(session: AsyncSession, order_id: int, status: str) -> Order | None:
    if status not in STATUSES:
        raise InvalidStatusError(status)
    order = await session.get(Order, order_id)
    if order is None:
        return None
    order.status = status
    await session.commit()
    return order
