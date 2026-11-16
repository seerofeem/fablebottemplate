from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import ClientConfig, load_client_config
from app.db import SessionFactory, create_engine, create_session_factory, init_db
from app.i18n import Translator, load_translator

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_CONFIG = ROOT / "client.yaml"
USER_ID = 42


@pytest.fixture
def raw_config() -> dict[str, Any]:
    with EXAMPLE_CONFIG.open(encoding="utf-8") as stream:
        data: dict[str, Any] = yaml.safe_load(stream)
    return data


@pytest.fixture
def config() -> ClientConfig:
    return load_client_config(EXAMPLE_CONFIG)


@pytest.fixture
def translator(config: ClientConfig) -> Translator:
    return load_translator(config.shop.languages)


@pytest.fixture
async def session_factory(tmp_path: Path) -> AsyncIterator[SessionFactory]:
    engine = create_engine(tmp_path / "data" / "test.db")
    await init_db(engine)
    yield create_session_factory(engine)
    await engine.dispose()


@pytest.fixture
async def session(session_factory: SessionFactory) -> AsyncIterator[AsyncSession]:
    async with session_factory() as active:
        yield active
