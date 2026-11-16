from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import ClientConfig, Product
from app.models import CartItem

MAX_QUANTITY = 99


class UnknownProductError(Exception):
    pass


@dataclass(frozen=True)
class CartLine:
    product: Product
    quantity: int

    @property
    def subtotal(self) -> int:
        return self.product.price * self.quantity


@dataclass(frozen=True)
class Cart:
    lines: tuple[CartLine, ...] = ()

    @property
    def total(self) -> int:
        return sum(line.subtotal for line in self.lines)

    @property
    def count(self) -> int:
        return sum(line.quantity for line in self.lines)

    @property
    def is_empty(self) -> bool:
        return not self.lines


def clamp_quantity(quantity: int) -> int:
    return max(0, min(MAX_QUANTITY, quantity))


async def get_cart(session: AsyncSession, config: ClientConfig, user_id: int) -> Cart:
    rows = await session.scalars(
        select(CartItem).where(CartItem.user_id == user_id).order_by(CartItem.product_id)
    )
    lines = []
    for row in rows:
        product = config.product(row.product_id)
        if product is not None and row.quantity > 0:
            lines.append(CartLine(product=product, quantity=row.quantity))
    order = {product.id: index for index, product in enumerate(config.products())}
    lines.sort(key=lambda line: order[line.product.id])
    return Cart(lines=tuple(lines))


async def change_quantity(
    session: AsyncSession, config: ClientConfig, user_id: int, product_id: str, delta: int
) -> int:
    if config.product(product_id) is None:
        raise UnknownProductError(product_id)
    item = await session.get(CartItem, (user_id, product_id))
    quantity = clamp_quantity((item.quantity if item is not None else 0) + delta)
    if quantity == 0:
        if item is not None:
            await session.delete(item)
    elif item is None:
        session.add(CartItem(user_id=user_id, product_id=product_id, quantity=quantity))
    else:
        item.quantity = quantity
    await session.commit()
    return quantity


async def remove_item(session: AsyncSession, user_id: int, product_id: str) -> None:
    await session.execute(
        delete(CartItem).where(CartItem.user_id == user_id, CartItem.product_id == product_id)
    )
    await session.commit()


async def clear_cart(session: AsyncSession, user_id: int) -> None:
    await session.execute(delete(CartItem).where(CartItem.user_id == user_id))
    await session.commit()
