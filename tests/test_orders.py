from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.bitrix import BitrixClient, BitrixError
from app.cart import change_quantity, get_cart
from app.config import ClientConfig
from app.i18n import Translator
from app.models import Order
from app.orders import (
    CheckoutData,
    EmptyCartError,
    InvalidStatusError,
    UnknownDeliveryError,
    place_order,
    recent_orders,
    set_status,
)
from tests.conftest import USER_ID

WEBHOOK = "https://example.bitrix24.kz/rest/1/secret-token/"
COURIER = CheckoutData(
    name="Айгерим", phone="+77011234567", delivery_id="courier", address="ул. Сатпаева 30, кв. 5"
)
PICKUP = CheckoutData(name="Данияр", phone="+77029876543", delivery_id="pickup", address="ignored")

Handler = Callable[[httpx.Request], httpx.Response]


class Outbox:
    def __init__(self, fail: bool = False) -> None:
        self.messages: list[tuple[int, str]] = []
        self.fail = fail

    async def __call__(self, chat_id: int, text: str) -> None:
        if self.fail:
            raise RuntimeError("telegram is down")
        self.messages.append((chat_id, text))


class Bitrix:
    def __init__(self, handler: Handler | None = None) -> None:
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self._handler = handler or self._success
        self.http = httpx.AsyncClient(transport=httpx.MockTransport(self._handle))
        self.client = BitrixClient(WEBHOOK, self.http, "Gül Almaty")

    def _handle(self, request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        self.requests.append((method, json.loads(request.content)))
        return self._handler(request)

    @staticmethod
    def _success(request: httpx.Request) -> httpx.Response:
        result = 55 if request.url.path.endswith("crm.contact.add.json") else 777
        return httpx.Response(200, json={"result": result, "time": {}})


async def fill_cart(session: AsyncSession, config: ClientConfig) -> None:
    await change_quantity(session, config, USER_ID, "roses_25", 2)
    await change_quantity(session, config, USER_ID, "card", 1)


async def test_order_creates_deal_and_notifies_owner(
    session: AsyncSession, config: ClientConfig, translator: Translator
) -> None:
    await fill_cart(session, config)
    bitrix = Bitrix()
    outbox = Outbox()

    order = await place_order(
        session, config, translator, USER_ID, "kk", COURIER, bitrix.client, outbox
    )

    assert order.id == 1
    assert order.items_total == 50500
    assert order.delivery_price == 1500
    assert order.total == 52000
    assert order.status == "new"
    assert order.lang == "kk"
    assert order.bitrix_deal_id == 777
    assert [(item.name, item.quantity, item.price) for item in order.items] == [
        ("25 красных роз", 2, 24900),
        ("Открытка с вашим текстом", 1, 700),
    ]
    assert (await get_cart(session, config, USER_ID)).is_empty

    assert [method for method, _ in bitrix.requests] == [
        "crm.contact.add.json",
        "crm.deal.add.json",
    ]
    contact = bitrix.requests[0][1]["fields"]
    assert contact["NAME"] == "Айгерим"
    assert contact["PHONE"] == [{"VALUE": "+77011234567", "VALUE_TYPE": "MOBILE"}]
    deal = bitrix.requests[1][1]["fields"]
    assert deal["CONTACT_IDS"] == [55]
    assert deal["OPPORTUNITY"] == 52000
    assert deal["CURRENCY_ID"] == "KZT"
    assert deal["TITLE"] == "Gül Almaty: Telegram #1"
    assert "25 красных роз x 2 = 49800" in deal["COMMENTS"]
    assert "ул. Сатпаева 30, кв. 5" in deal["COMMENTS"]

    assert len(outbox.messages) == 1
    chat_id, text = outbox.messages[0]
    assert chat_id == config.owner_chat_id
    assert "Новый заказ №1" in text
    assert "Айгерим" in text
    assert "+77011234567" in text
    assert "ул. Сатпаева 30, кв. 5" in text
    assert "Итого: 52 000 ₸" in text
    assert "Bitrix24: сделка №777" in text

    await session.refresh(order)
    assert order.bitrix_deal_id == 777


def http_500(request: httpx.Request) -> httpx.Response:
    return httpx.Response(500, text="<html>Internal Server Error</html>")


def access_denied(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        401,
        json={"error": "INVALID_CREDENTIALS", "error_description": "Invalid request credentials"},
    )


def timeout(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectTimeout("timed out", request=request)


def invalid_json(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, text="not json")


def no_result(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"time": {}})


def deal_fails_after_contact(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("crm.contact.add.json"):
        return httpx.Response(200, json={"result": 55})
    return httpx.Response(400, json={"error": "", "error_description": "Deal title is required"})


@pytest.mark.parametrize(
    "handler", [http_500, access_denied, timeout, invalid_json, no_result, deal_fails_after_contact]
)
async def test_crm_failure_keeps_order_and_notifies_owner(
    session: AsyncSession,
    config: ClientConfig,
    translator: Translator,
    caplog: pytest.LogCaptureFixture,
    handler: Handler,
) -> None:
    await fill_cart(session, config)
    bitrix = Bitrix(handler)
    outbox = Outbox()

    with caplog.at_level(logging.ERROR, logger="app.orders"):
        order = await place_order(
            session, config, translator, USER_ID, "ru", COURIER, bitrix.client, outbox
        )

    assert order.bitrix_deal_id is None
    saved = await session.get(Order, order.id)
    assert saved is not None
    assert saved.total == 52000
    assert (await get_cart(session, config, USER_ID)).is_empty
    assert len(outbox.messages) == 1
    assert "Новый заказ №1" in outbox.messages[0][1]
    assert "сделку создать не удалось" in outbox.messages[0][1]
    assert "Bitrix24 deal for order 1 failed" in caplog.text
    assert "secret-token" not in caplog.text


async def test_crm_error_does_not_leak_webhook_secret() -> None:
    bitrix = Bitrix(http_500)
    order = Order(id=1, user_id=USER_ID, customer_name="A", phone="+77010000000", total=1)
    with pytest.raises(BitrixError) as error:
        await bitrix.client.create_deal(order)
    assert "secret-token" not in str(error.value)
    assert error.value.__cause__ is None


async def test_crm_disabled_sends_only_owner_message(
    session: AsyncSession, config: ClientConfig, translator: Translator
) -> None:
    await fill_cart(session, config)
    outbox = Outbox()

    order = await place_order(session, config, translator, USER_ID, "ru", PICKUP, None, outbox)

    assert order.bitrix_deal_id is None
    assert order.total == 50500
    assert order.address == ""
    assert len(outbox.messages) == 1
    assert "Bitrix24" not in outbox.messages[0][1]
    assert "Самовывоз" in outbox.messages[0][1]


async def test_owner_notification_failure_keeps_order(
    session: AsyncSession, config: ClientConfig, translator: Translator
) -> None:
    await fill_cart(session, config)
    order = await place_order(
        session, config, translator, USER_ID, "ru", PICKUP, None, Outbox(fail=True)
    )
    assert await session.get(Order, order.id) is not None


async def test_owner_message_escapes_customer_input(
    session: AsyncSession, config: ClientConfig, translator: Translator
) -> None:
    await fill_cart(session, config)
    outbox = Outbox()
    data = CheckoutData(
        name="<b>Bob</b>", phone="+77010000000", delivery_id="courier", address="A&B"
    )
    await place_order(session, config, translator, USER_ID, "ru", data, None, outbox)
    assert "&lt;b&gt;Bob&lt;/b&gt;" in outbox.messages[0][1]
    assert "A&amp;B" in outbox.messages[0][1]


async def test_empty_cart_is_rejected(
    session: AsyncSession, config: ClientConfig, translator: Translator
) -> None:
    outbox = Outbox()
    with pytest.raises(EmptyCartError):
        await place_order(session, config, translator, USER_ID, "ru", PICKUP, None, outbox)
    assert outbox.messages == []
    assert await recent_orders(session) == []


async def test_unknown_delivery_is_rejected(
    session: AsyncSession, config: ClientConfig, translator: Translator
) -> None:
    await fill_cart(session, config)
    data = CheckoutData(name="A", phone="+77010000000", delivery_id="drone")
    with pytest.raises(UnknownDeliveryError):
        await place_order(session, config, translator, USER_ID, "ru", data, None, Outbox())
    assert not (await get_cart(session, config, USER_ID)).is_empty


async def test_recent_orders_and_status(
    session: AsyncSession, config: ClientConfig, translator: Translator
) -> None:
    for _ in range(12):
        await change_quantity(session, config, USER_ID, "card", 1)
        await place_order(session, config, translator, USER_ID, "ru", PICKUP, None, Outbox())

    orders = await recent_orders(session)
    assert [order.id for order in orders] == list(range(12, 2, -1))

    updated = await set_status(session, 12, "done")
    assert updated is not None and updated.status == "done"
    assert await set_status(session, 999, "done") is None
    with pytest.raises(InvalidStatusError):
        await set_status(session, 12, "shipped")
