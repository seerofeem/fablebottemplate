from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import (
    AnswerCallbackQuery,
    EditMessageText,
    SendMessage,
    SendPhoto,
    TelegramMethod,
)
from aiogram.types import Chat, Message
from sqlalchemy import select

from app.config import ClientConfig
from app.db import SessionFactory
from app.handlers.checkout import normalize_phone
from app.handlers.owner import parse_status_args
from app.i18n import Translator
from app.main import build_dispatcher
from app.models import Order
from tests.conftest import USER_ID

TOKEN = "123456:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"


class RecordingSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[TelegramMethod[Any]] = []
        self.fail_photos = False

    async def close(self) -> None:
        return None

    async def make_request(
        self, bot: Bot, method: TelegramMethod[Any], timeout: int | None = None
    ) -> Any:
        self.calls.append(method)
        if isinstance(method, AnswerCallbackQuery):
            return True
        if isinstance(method, SendPhoto) and self.fail_photos:
            raise TelegramBadRequest(method=method, message="wrong file identifier")
        chat_id = int(getattr(method, "chat_id", USER_ID))
        return Message(
            message_id=len(self.calls),
            date=datetime.now(UTC),
            chat=Chat(id=chat_id, type="private"),
        )

    async def stream_content(
        self,
        url: str,
        headers: dict[str, Any] | None = None,
        timeout: int = 30,
        chunk_size: int = 65536,
        raise_for_status: bool = True,
    ) -> AsyncGenerator[bytes, None]:
        yield b""


class Client:
    def __init__(self, dispatcher: Dispatcher, bot: Bot, session: RecordingSession) -> None:
        self._dispatcher = dispatcher
        self._bot = bot
        self._session = session
        self._update_id = 0

    def _base(self, chat_id: int) -> dict[str, Any]:
        return {
            "message_id": 1000 + self._update_id,
            "date": 1795000000,
            "chat": {"id": chat_id, "type": "private"},
            "from": {"id": chat_id, "is_bot": False, "first_name": "Test"},
        }

    async def _feed(self, update: dict[str, Any]) -> list[TelegramMethod[Any]]:
        self._update_id += 1
        start = len(self._session.calls)
        await self._dispatcher.feed_raw_update(self._bot, {"update_id": self._update_id, **update})
        return self._session.calls[start:]

    async def text(self, text: str, chat_id: int = USER_ID) -> list[TelegramMethod[Any]]:
        message = {**self._base(chat_id), "text": text}
        if text.startswith("/"):
            length = len(text.split()[0])
            message["entities"] = [{"type": "bot_command", "offset": 0, "length": length}]
        return await self._feed({"message": message})

    async def contact(self, phone: str, chat_id: int = USER_ID) -> list[TelegramMethod[Any]]:
        contact = {"phone_number": phone, "first_name": "Test", "user_id": chat_id}
        return await self._feed({"message": {**self._base(chat_id), "contact": contact}})

    async def press(self, data: str, chat_id: int = USER_ID) -> list[TelegramMethod[Any]]:
        base = self._base(chat_id)
        callback = {
            "id": str(self._update_id),
            "from": base["from"],
            "chat_instance": "test",
            "data": data,
            "message": {**base, "text": "previous"},
        }
        return await self._feed({"callback_query": callback})


def texts(calls: list[TelegramMethod[Any]]) -> list[str]:
    result = []
    for call in calls:
        if isinstance(call, SendMessage | EditMessageText):
            result.append(str(call.text))
        elif isinstance(call, SendPhoto):
            result.append(str(call.caption))
        elif isinstance(call, AnswerCallbackQuery) and call.text:
            result.append(call.text)
    return result


@pytest.fixture
def telegram() -> RecordingSession:
    return RecordingSession()


@pytest.fixture
async def client(
    config: ClientConfig,
    translator: Translator,
    session_factory: SessionFactory,
    telegram: RecordingSession,
) -> AsyncIterator[Client]:
    bot = Bot(TOKEN, session=telegram)
    dispatcher = build_dispatcher(config, translator, session_factory, None)
    yield Client(dispatcher, bot, telegram)
    await dispatcher.storage.close()


async def fetch_orders(session_factory: SessionFactory) -> list[Order]:
    async with session_factory() as session:
        return list(await session.scalars(select(Order).order_by(Order.id)))


async def test_full_customer_flow(
    client: Client, config: ClientConfig, session_factory: SessionFactory
) -> None:
    calls = await client.text("/start")
    assert "Выберите язык" in texts(calls)[0]

    calls = await client.press("lang:ru")
    assert "Gül Almaty" in texts(calls)[-1]
    assert "Свежие букеты" in texts(calls)[-1]

    calls = await client.press("catalog")
    assert texts(calls) == ["Выберите категорию:"]

    calls = await client.press("cat:bouquets")
    photos = [call for call in calls if isinstance(call, SendPhoto)]
    assert len(photos) == 3
    assert "25 красных роз" in str(photos[0].caption)
    assert "24 900 ₸" in str(photos[0].caption)

    await client.press("add:roses_25")
    calls = await client.press("add:roses_25")
    assert texts(calls) == ["В корзине: 25 красных роз × 2"]
    await client.press("add:card")
    await client.press("add:card")

    calls = await client.press("cart")
    assert "Итого: 51 200 ₸" in texts(calls)[-1]

    calls = await client.press("dec:card")
    edits = [call for call in calls if isinstance(call, EditMessageText)]
    assert len(edits) == 1
    assert "Итого: 50 500 ₸" in str(edits[0].text)

    calls = await client.press("inc:vase")
    assert "Итого: 57 000 ₸" in texts(calls)[-1]
    calls = await client.press("del:vase")
    assert "Итого: 50 500 ₸" in texts(calls)[-1]

    calls = await client.press("checkout")
    assert texts(calls) == ["Как вас зовут?"]

    calls = await client.text("А")
    assert "от 2 до 64" in texts(calls)[0]
    calls = await client.text("Айгерим")
    assert "номер телефона" in texts(calls)[0]

    calls = await client.text("позвоните мне")
    assert "Не похоже на номер" in texts(calls)[0]
    calls = await client.contact("77011234567")
    assert texts(calls)[0] == "Номер сохранён: +77011234567"
    assert "способ получения" in texts(calls)[1]

    calls = await client.press("dlv:courier")
    assert "адрес доставки" in texts(calls)[-1]

    calls = await client.text("ул. Сатпаева 30, кв. 5")
    summary = texts(calls)[-1]
    assert "Проверьте заказ" in summary
    assert "Айгерим" in summary
    assert "+77011234567" in summary
    assert "ул. Сатпаева 30, кв. 5" in summary
    assert "Итого: 52 000 ₸" in summary

    calls = await client.press("confirm")
    messages = [call for call in calls if isinstance(call, SendMessage)]
    assert [message.chat_id for message in messages] == [config.owner_chat_id, USER_ID]
    assert "Новый заказ №1" in str(messages[0].text)
    assert "Итого: 52 000 ₸" in str(messages[0].text)
    assert "Заказ №1 принят" in str(messages[1].text)

    orders = await fetch_orders(session_factory)
    assert len(orders) == 1
    assert orders[0].total == 52000
    assert orders[0].customer_name == "Айгерим"
    assert orders[0].address == "ул. Сатпаева 30, кв. 5"

    calls = await client.press("cart")
    assert "Корзина пуста" in texts(calls)[-1]

    calls = await client.press("confirm")
    assert "Оформление устарело" in texts(calls)[-1]
    assert len(await fetch_orders(session_factory)) == 1


async def test_kazakh_pickup_flow_with_typed_phone(
    client: Client, session_factory: SessionFactory
) -> None:
    await client.text("/start")
    calls = await client.press("lang:kk")
    assert "жаңа гүл шоқтары" in texts(calls)[-1]

    await client.press("add:box_pastel")
    calls = await client.press("checkout")
    assert texts(calls) == ["Атыңыз кім?"]
    await client.text("Данияр")
    calls = await client.text("8 (702) 987-65-43")
    assert texts(calls)[0] == "Нөмір сақталды: +77029876543"

    calls = await client.press("dlv:pickup")
    assert "Тапсырысты тексеріңіз" in texts(calls)[-1]
    assert "Барлығы: 18 900 ₸" in texts(calls)[-1]

    calls = await client.press("confirm")
    assert "№1 тапсырыс қабылданды" in texts(calls)[-1]
    orders = await fetch_orders(session_factory)
    assert orders[0].lang == "kk"
    assert orders[0].address == ""
    assert orders[0].delivery_name == "Самовывоз, пр. Абая 52"


async def test_cancel_keeps_cart(client: Client, session_factory: SessionFactory) -> None:
    await client.press("lang:ru")
    await client.press("add:card")
    await client.press("checkout")
    await client.text("Айгерим")
    calls = await client.press("cancel")
    assert "Оформление отменено" in texts(calls)[-1]
    calls = await client.text("просто текст")
    assert calls == []
    calls = await client.press("cart")
    assert "Итого: 700 ₸" in texts(calls)[-1]
    assert await fetch_orders(session_factory) == []


async def test_checkout_with_empty_cart_shows_alert(client: Client) -> None:
    calls = await client.press("checkout")
    assert texts(calls) == ["Корзина пуста. Загляните в каталог!"]


async def test_photo_failure_falls_back_to_text(client: Client, telegram: RecordingSession) -> None:
    telegram.fail_photos = True
    calls = await client.press("cat:boxes")
    messages = [call for call in calls if isinstance(call, SendMessage)]
    assert len(messages) == 3
    assert "Коробка «Пастель»" in str(messages[0].text)


async def test_products_without_photo_are_sent_as_text(client: Client) -> None:
    calls = await client.press("cat:extras")
    assert not [call for call in calls if isinstance(call, SendPhoto)]
    assert len([call for call in calls if isinstance(call, SendMessage)]) == 3


async def test_owner_commands(client: Client, config: ClientConfig) -> None:
    owner = config.owner_chat_id
    calls = await client.text("/orders", chat_id=owner)
    assert texts(calls) == ["Заказов пока нет."]

    await client.press("lang:kk")
    await client.press("add:card")
    await client.press("checkout")
    await client.text("Данияр")
    await client.text("+77029876543")
    await client.press("dlv:pickup")
    await client.press("confirm")

    calls = await client.text("/orders", chat_id=owner)
    assert "№1" in texts(calls)[0]
    assert "Данияр" in texts(calls)[0]
    assert "700 ₸" in texts(calls)[0]
    assert "новый" in texts(calls)[0]

    calls = await client.text("/status 1 done", chat_id=owner)
    messages = [call for call in calls if isinstance(call, SendMessage)]
    assert [message.chat_id for message in messages] == [owner, USER_ID]
    assert "выполнен" in str(messages[0].text)
    assert "орындалды" in str(messages[1].text)

    calls = await client.text("/orders", chat_id=owner)
    assert "выполнен" in texts(calls)[0]

    calls = await client.text("/status 99 done", chat_id=owner)
    assert "не найден" in texts(calls)[0]
    calls = await client.text("/status 1 shipped", chat_id=owner)
    assert "Формат: /status" in texts(calls)[0]


async def test_owner_commands_are_ignored_for_customers(client: Client) -> None:
    assert await client.text("/orders") == []
    assert await client.text("/status 1 done") == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+7 701 123 45 67", "+77011234567"),
        ("87011234567", "+77011234567"),
        ("77011234567", "+77011234567"),
        ("7011234567", "+7011234567"),
        ("12345", None),
        ("call me", None),
        ("+7701123456x", None),
        ("", None),
    ],
)
def test_normalize_phone(raw: str, expected: str | None) -> None:
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ("5 done", (5, "done")),
        ("#5 CANCELLED", (5, "cancelled")),
        ("5", None),
        ("five done", None),
        ("5 shipped", None),
        (None, None),
    ],
)
def test_parse_status_args(args: str | None, expected: tuple[int, str] | None) -> None:
    assert parse_status_args(args) == expected
