from __future__ import annotations

import asyncio
import logging

import httpx
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from app.bitrix import BitrixClient
from app.config import ClientConfig, Settings, load_client_config
from app.db import SessionFactory, create_engine, create_session_factory, init_db
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
) -> Dispatcher:
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher["config"] = config
    dispatcher["translator"] = translator
    dispatcher["crm"] = crm
    dispatcher.update.outer_middleware(ContextMiddleware(session_factory, config))
    for module in (start, owner, catalog, cart, checkout):
        dispatcher.include_router(module.router.build())
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
        bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        dispatcher = build_dispatcher(config, translator, create_session_factory(engine), crm)
        logger.info(
            "Starting %s, languages=%s, crm_enabled=%s",
            config.shop.name,
            ",".join(config.shop.languages),
            settings.crm_enabled,
        )
        try:
            await dispatcher.start_polling(bot)
        finally:
            await bot.session.close()
            await engine.dispose()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
