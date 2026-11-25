from __future__ import annotations

import asyncio
import logging
import sys

import anthropic
import httpx
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramUnauthorizedError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.token import TokenValidationError
from pydantic import ValidationError

from app.assistant import Answerer, ClaudeAssistant, DailyLimit
from app.bitrix import BitrixClient
from app.config import ClientConfig, Settings, load_client_config
from app.db import SessionFactory, create_engine, create_session_factory, init_db
from app.handlers import assistant as assistant_handlers
from app.handlers import cart, catalog, checkout, owner, start
from app.handlers.common import ContextMiddleware
from app.i18n import Translator, load_translator
from app.orders import DealCreator

logger = logging.getLogger(__name__)


def build_dispatcher(
    config: ClientConfig,
    translator: Translator,
    session_factory: SessionFactory,
    crm: DealCreator | None,
    assistant: Answerer | None = None,
    assistant_daily_limit: int = 20,
) -> Dispatcher:
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher["config"] = config
    dispatcher["translator"] = translator
    dispatcher["crm"] = crm
    dispatcher["assistant"] = assistant
    dispatcher["assistant_limit"] = DailyLimit(assistant_daily_limit)
    dispatcher.update.outer_middleware(ContextMiddleware(session_factory, config))
    for module in (start, owner, catalog, cart, checkout):
        dispatcher.include_router(module.router.build())
    if assistant is not None:
        dispatcher.include_router(assistant_handlers.router.build())
    return dispatcher


async def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = Settings()
    config = load_client_config(settings.client_config)
    translator = load_translator(config.shop.languages)
    engine = create_engine(settings.database_path)
    await init_db(engine)
    async with httpx.AsyncClient() as http:
        crm: DealCreator | None = None
        if settings.crm_enabled:
            crm = BitrixClient(settings.bitrix_webhook_url, http, config.shop.name)
        claude: anthropic.AsyncAnthropic | None = None
        assistant: Answerer | None = None
        if settings.assistant_enabled:
            claude = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
            assistant = ClaudeAssistant(claude, config, settings.assistant_model)
        bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        dispatcher = build_dispatcher(
            config,
            translator,
            create_session_factory(engine),
            crm,
            assistant,
            settings.assistant_daily_limit,
        )
        logger.info(
            "Starting %s, languages=%s, crm_enabled=%s, assistant_enabled=%s",
            config.shop.name,
            ",".join(config.shop.languages),
            settings.crm_enabled,
            settings.assistant_enabled,
        )
        try:
            await dispatcher.start_polling(bot)
        finally:
            await bot.session.close()
            if claude is not None:
                await claude.close()
            await engine.dispose()


def main() -> None:
    try:
        asyncio.run(run())
    except (ValidationError, ValueError, OSError) as exc:
        logger.error("Configuration error, fix .env or client.yaml: %s", exc)
        sys.exit(1)
    except (TokenValidationError, TelegramUnauthorizedError):
        logger.error("Telegram rejected BOT_TOKEN, check the value in .env")
        sys.exit(1)


if __name__ == "__main__":
    main()
