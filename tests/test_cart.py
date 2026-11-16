from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.cart import (
    MAX_QUANTITY,
    Cart,
    CartLine,
    UnknownProductError,
    change_quantity,
    clear_cart,
    get_cart,
    remove_item,
)
from app.config import ClientConfig
from app.i18n import Translator
from app.texts import cart_text, format_money
from tests.conftest import USER_ID


def test_cart_math(config: ClientConfig) -> None:
    roses = config.product("roses_25")
    card = config.product("card")
    assert roses is not None and card is not None
    cart = Cart(lines=(CartLine(roses, 2), CartLine(card, 3)))
    assert cart.lines[0].subtotal == 49800
    assert cart.lines[1].subtotal == 2100
    assert cart.total == 51900
    assert cart.count == 5
    assert not cart.is_empty


def test_empty_cart() -> None:
    cart = Cart()
    assert cart.total == 0
    assert cart.count == 0
    assert cart.is_empty


@pytest.mark.parametrize(
    ("amount", "currency", "expected"),
    [
        (0, "KZT", "0 ₸"),
        (700, "KZT", "700 ₸"),
        (1234567, "KZT", "1 234 567 ₸"),
        (500, "GBP", "500 GBP"),
    ],
)
def test_format_money(amount: int, currency: str, expected: str) -> None:
    assert format_money(amount, currency) == expected


async def test_add_and_total(session: AsyncSession, config: ClientConfig) -> None:
    assert await change_quantity(session, config, USER_ID, "roses_25", 1) == 1
    assert await change_quantity(session, config, USER_ID, "roses_25", 1) == 2
    assert await change_quantity(session, config, USER_ID, "vase", 1) == 1
    cart = await get_cart(session, config, USER_ID)
    assert [(line.product.id, line.quantity) for line in cart.lines] == [
        ("roses_25", 2),
        ("vase", 1),
    ]
    assert cart.total == 2 * 24900 + 6500


async def test_decrease_to_zero_removes_line(session: AsyncSession, config: ClientConfig) -> None:
    await change_quantity(session, config, USER_ID, "card", 2)
    assert await change_quantity(session, config, USER_ID, "card", -1) == 1
    assert await change_quantity(session, config, USER_ID, "card", -1) == 0
    assert await change_quantity(session, config, USER_ID, "card", -1) == 0
    assert (await get_cart(session, config, USER_ID)).is_empty


async def test_quantity_is_capped(session: AsyncSession, config: ClientConfig) -> None:
    assert await change_quantity(session, config, USER_ID, "card", 500) == MAX_QUANTITY
    assert await change_quantity(session, config, USER_ID, "card", 1) == MAX_QUANTITY


async def test_unknown_product_is_rejected(session: AsyncSession, config: ClientConfig) -> None:
    with pytest.raises(UnknownProductError):
        await change_quantity(session, config, USER_ID, "missing", 1)


async def test_remove_and_clear(session: AsyncSession, config: ClientConfig) -> None:
    await change_quantity(session, config, USER_ID, "roses_25", 1)
    await change_quantity(session, config, USER_ID, "card", 1)
    await remove_item(session, USER_ID, "roses_25")
    cart = await get_cart(session, config, USER_ID)
    assert [line.product.id for line in cart.lines] == ["card"]
    await clear_cart(session, USER_ID)
    assert (await get_cart(session, config, USER_ID)).is_empty


async def test_carts_are_per_user(session: AsyncSession, config: ClientConfig) -> None:
    await change_quantity(session, config, USER_ID, "card", 1)
    await change_quantity(session, config, USER_ID + 1, "vase", 2)
    assert (await get_cart(session, config, USER_ID)).total == 700
    assert (await get_cart(session, config, USER_ID + 1)).total == 13000


async def test_products_removed_from_config_are_skipped(
    session: AsyncSession, config: ClientConfig
) -> None:
    await change_quantity(session, config, USER_ID, "card", 1)
    await change_quantity(session, config, USER_ID, "vase", 1)
    data = config.model_dump(mode="json")
    data["categories"][2]["products"] = [data["categories"][2]["products"][0]]
    smaller = ClientConfig.model_validate(data)
    cart = await get_cart(session, smaller, USER_ID)
    assert [line.product.id for line in cart.lines] == ["card"]
    assert cart.total == 700


async def test_cart_text_shows_lines_and_total(
    session: AsyncSession, config: ClientConfig, translator: Translator
) -> None:
    await change_quantity(session, config, USER_ID, "roses_25", 2)
    text = cart_text(translator, "ru", await get_cart(session, config, USER_ID), "KZT")
    assert "1. 25 красных роз — 2 × 24 900 ₸ = 49 800 ₸" in text
    assert "Итого: 49 800 ₸" in text
    assert "Себет бос" in cart_text(translator, "kk", Cart(), "KZT")
