from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx
import pytest
from aiogram import Bot
from aiogram.methods import SendChatAction
from pydantic import ValidationError

from app.assistant import ClaudeAssistant, DailyLimit, shop_context
from app.config import ClientConfig, Settings
from app.db import SessionFactory
from app.i18n import Translator
from app.main import build_dispatcher
from tests.test_bot_flow import TOKEN, Client, RecordingSession, texts


class FakeAnswerer:
    def __init__(self, reply: str | None = "Пионы стоят 31 000 ₸.") -> None:
        self.reply = reply
        self.questions: list[tuple[str, str]] = []

    async def answer(self, question: str, lang: str) -> str | None:
        self.questions.append((question, lang))
        return self.reply


@pytest.fixture
def answerer() -> FakeAnswerer:
    return FakeAnswerer()


async def make_client(
    config: ClientConfig,
    translator: Translator,
    session_factory: SessionFactory,
    answerer: FakeAnswerer | None,
) -> AsyncIterator[Client]:
    recorder = RecordingSession()
    dispatcher = build_dispatcher(config, translator, session_factory, None, answerer, 2)
    yield Client(dispatcher, Bot(TOKEN, session=recorder), recorder)
    await dispatcher.storage.close()


@pytest.fixture
async def ai_client(
    config: ClientConfig,
    translator: Translator,
    session_factory: SessionFactory,
    answerer: FakeAnswerer,
) -> AsyncIterator[Client]:
    async for active in make_client(config, translator, session_factory, answerer):
        yield active


@pytest.fixture
async def plain_client(
    config: ClientConfig, translator: Translator, session_factory: SessionFactory
) -> AsyncIterator[Client]:
    async for active in make_client(config, translator, session_factory, None):
        yield active


async def test_question_gets_escaped_answer(ai_client: Client, answerer: FakeAnswerer) -> None:
    await ai_client.text("/start")
    await ai_client.press("lang:kk")
    answerer.reply = "<b>9 пион</b> — 31 000 ₸"
    calls = await ai_client.text("Пиондар қанша тұрады?")
    assert any(isinstance(call, SendChatAction) for call in calls)
    assert texts(calls) == ["&lt;b&gt;9 пион&lt;/b&gt; — 31 000 ₸"]
    assert answerer.questions == [("Пиондар қанша тұрады?", "kk")]


async def test_menu_shows_hint_when_assistant_is_on(ai_client: Client) -> None:
    await ai_client.text("/start")
    calls = await ai_client.press("lang:ru")
    assert "Можете задать вопрос текстом" in texts(calls)[-1]


async def test_menu_has_no_hint_when_assistant_is_off(plain_client: Client) -> None:
    await plain_client.text("/start")
    calls = await plain_client.press("lang:ru")
    assert "Можете задать вопрос" not in texts(calls)[-1]


async def test_free_text_is_ignored_when_assistant_is_off(plain_client: Client) -> None:
    assert texts(await plain_client.text("Сколько стоят пионы?")) == []


async def test_daily_limit(ai_client: Client, answerer: FakeAnswerer) -> None:
    await ai_client.text("Вопрос 1")
    await ai_client.text("Вопрос 2")
    calls = await ai_client.text("Вопрос 3")
    assert "лимит вопросов исчерпан" in texts(calls)[0]
    assert len(answerer.questions) == 2


async def test_failed_answer_shows_fallback(ai_client: Client, answerer: FakeAnswerer) -> None:
    answerer.reply = None
    calls = await ai_client.text("Есть ли скидки?")
    assert "Не получилось ответить" in texts(calls)[0]


async def test_checkout_input_is_not_sent_to_assistant(
    ai_client: Client, answerer: FakeAnswerer
) -> None:
    await ai_client.press("add:roses_25")
    await ai_client.press("checkout")
    calls = await ai_client.text("Айгерим")
    assert "номер телефона" in texts(calls)[0]
    assert answerer.questions == []


async def test_owner_chat_is_not_answered(
    ai_client: Client, answerer: FakeAnswerer, config: ClientConfig
) -> None:
    assert texts(await ai_client.text("привет", chat_id=config.owner_chat_id)) == []
    assert answerer.questions == []


def test_shop_context_lists_facts(config: ClientConfig) -> None:
    context = shop_context(config, "ru")
    assert "Gül Almaty" in context
    assert "9 пионов, 31 000 ₸" in context
    assert "Самовывоз, пр. Абая 52: free" in context
    assert "- sun: 10:00-20:00" in context
    assert "Kaspi QR" in context


def test_daily_limit_resets_next_day() -> None:
    limit = DailyLimit(1)
    assert limit.take(1, date(2026, 1, 1))
    assert not limit.take(1, date(2026, 1, 1))
    assert limit.take(2, date(2026, 1, 1))
    assert limit.take(1, date(2026, 1, 2))


def test_settings_require_key_when_assistant_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", TOKEN)
    monkeypatch.setenv("ASSISTANT_ENABLED", "true")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ValidationError, match="ANTHROPIC_API_KEY"):
        Settings(_env_file=None)  # type: ignore[call-arg]


class FakeMessages:
    def __init__(self, outcome: Any) -> None:
        self.outcome = outcome
        self.kwargs: dict[str, Any] = {}

    async def create(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def fake_claude(outcome: Any) -> tuple[Any, FakeMessages]:
    messages = FakeMessages(outcome)
    return SimpleNamespace(beta=SimpleNamespace(messages=messages)), messages


def response(text: str, stop_reason: str = "end_turn") -> Any:
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[
            SimpleNamespace(type="thinking", thinking=""),
            SimpleNamespace(type="text", text=text),
        ],
        _request_id="req_test",
    )


async def test_claude_assistant_request_and_answer(config: ClientConfig) -> None:
    claude, messages = fake_claude(response("  Пионы стоят 31 000 ₸.  "))
    assistant = ClaudeAssistant(claude, config, "claude-opus-5-5")
    assert await assistant.answer("Сколько стоят пионы?", "ru") == "Пионы стоят 31 000 ₸."
    assert messages.kwargs["model"] == "claude-opus-5-5"
    assert messages.kwargs["fallbacks"] == "default"
    assert messages.kwargs["output_config"] == {"effort": "low"}
    assert "Reply in Russian" in messages.kwargs["system"][0]["text"]
    assert "9 пионов, 31 000 ₸" in messages.kwargs["system"][0]["text"]
    assert messages.kwargs["messages"] == [{"role": "user", "content": "Сколько стоят пионы?"}]


async def test_claude_assistant_uses_kazakh_context(config: ClientConfig) -> None:
    claude, messages = fake_claude(response("Иә."))
    await ClaudeAssistant(claude, config, "claude-opus-5-5").answer("Сәлем", "kk")
    assert "Reply in Kazakh" in messages.kwargs["system"][0]["text"]
    assert "9 пион, 31 000 ₸" in messages.kwargs["system"][0]["text"]


async def test_claude_assistant_refusal_returns_none(config: ClientConfig) -> None:
    claude, _ = fake_claude(response("", stop_reason="refusal"))
    assert await ClaudeAssistant(claude, config, "claude-opus-5-5").answer("?", "ru") is None


async def test_claude_assistant_api_errors_return_none(config: ClientConfig) -> None:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    errors: list[Exception] = [
        anthropic.APIConnectionError(request=request),
        anthropic.InternalServerError(
            "boom", response=httpx.Response(500, request=request), body=None
        ),
        anthropic.RateLimitError("slow", response=httpx.Response(429, request=request), body=None),
    ]
    for error in errors:
        claude, _ = fake_claude(error)
        assert await ClaudeAssistant(claude, config, "claude-opus-5-5").answer("?", "ru") is None


async def test_claude_assistant_truncates_long_question(config: ClientConfig) -> None:
    claude, messages = fake_claude(response("ok"))
    await ClaudeAssistant(claude, config, "claude-opus-5-5").answer("x" * 2000, "ru")
    assert len(messages.kwargs["messages"][0]["content"]) == 500
