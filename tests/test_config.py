from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
import yaml
from pydantic import ValidationError

from app.config import ClientConfig, Settings, load_client_config
from app.i18n import Markup, Translator

ALMATY = ZoneInfo("Asia/Almaty")


def test_example_config_is_valid(config: ClientConfig) -> None:
    assert config.shop.name == "Gül Almaty"
    assert config.shop.languages == ["ru", "kk"]
    assert config.default_language == "ru"
    assert config.shop.currency == "KZT"
    assert len(config.categories) == 3
    assert len(config.products()) == 7
    assert config.product("roses_25") is not None
    assert config.product("missing") is None
    assert config.delivery_option("pickup") is not None


def test_load_from_file(tmp_path: Path, raw_config: dict[str, Any]) -> None:
    raw_config["shop"]["name"] = "Cafe"
    path = tmp_path / "client.yaml"
    path.write_text(yaml.safe_dump(raw_config, allow_unicode=True), encoding="utf-8")
    assert load_client_config(path).shop.name == "Cafe"


def test_non_mapping_file_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "client.yaml"
    path.write_text("- just\n- a list\n", encoding="utf-8")
    with pytest.raises(ValueError, match="mapping"):
        load_client_config(path)


def test_missing_translation_is_rejected(raw_config: dict[str, Any]) -> None:
    del raw_config["categories"][0]["products"][0]["name"]["kk"]
    with pytest.raises(ValidationError, match="product roses_25 name"):
        ClientConfig.model_validate(raw_config)


def test_single_language_needs_only_that_language(raw_config: dict[str, Any]) -> None:
    raw_config["shop"]["languages"] = ["ru"]
    del raw_config["categories"][0]["products"][0]["name"]["kk"]
    assert ClientConfig.model_validate(raw_config).default_language == "ru"


def test_unsupported_language_is_rejected(raw_config: dict[str, Any]) -> None:
    raw_config["shop"]["languages"] = ["ru", "en"]
    with pytest.raises(ValidationError, match="unsupported languages"):
        ClientConfig.model_validate(raw_config)


def test_duplicate_product_ids_are_rejected(raw_config: dict[str, Any]) -> None:
    raw_config["categories"][1]["products"][0]["id"] = "roses_25"
    with pytest.raises(ValidationError, match="duplicate product ids: roses_25"):
        ClientConfig.model_validate(raw_config)


@pytest.mark.parametrize("price", [0, -100])
def test_non_positive_product_price_is_rejected(raw_config: dict[str, Any], price: int) -> None:
    raw_config["categories"][0]["products"][0]["price"] = price
    with pytest.raises(ValidationError):
        ClientConfig.model_validate(raw_config)


def test_negative_delivery_price_is_rejected(raw_config: dict[str, Any]) -> None:
    raw_config["delivery"][0]["price"] = -1
    with pytest.raises(ValidationError):
        ClientConfig.model_validate(raw_config)


@pytest.mark.parametrize("bad_id", ["Has Space", "UPPER", "x" * 33, ""])
def test_bad_identifier_is_rejected(raw_config: dict[str, Any], bad_id: str) -> None:
    raw_config["categories"][0]["id"] = bad_id
    with pytest.raises(ValidationError):
        ClientConfig.model_validate(raw_config)


@pytest.mark.parametrize("hours", ["9-21", "25:00-26:00", "21:00-09:00", "open"])
def test_bad_working_hours_are_rejected(raw_config: dict[str, Any], hours: str) -> None:
    raw_config["working_hours"]["mon"] = hours
    with pytest.raises(ValidationError):
        ClientConfig.model_validate(raw_config)


def test_missing_weekday_is_rejected(raw_config: dict[str, Any]) -> None:
    del raw_config["working_hours"]["sun"]
    with pytest.raises(ValidationError, match="working_hours"):
        ClientConfig.model_validate(raw_config)


def test_unknown_field_is_rejected(raw_config: dict[str, Any]) -> None:
    raw_config["shop"]["slogan"] = "typo"
    with pytest.raises(ValidationError):
        ClientConfig.model_validate(raw_config)


def test_unknown_timezone_is_rejected(raw_config: dict[str, Any]) -> None:
    raw_config["shop"]["timezone"] = "Asia/Nowhere"
    with pytest.raises(ValidationError, match="unknown timezone"):
        ClientConfig.model_validate(raw_config)


def test_zero_owner_chat_is_rejected(raw_config: dict[str, Any]) -> None:
    raw_config["owner_chat_id"] = 0
    with pytest.raises(ValidationError):
        ClientConfig.model_validate(raw_config)


def test_working_hours(raw_config: dict[str, Any]) -> None:
    raw_config["working_hours"]["sun"] = "closed"
    config = ClientConfig.model_validate(raw_config)
    assert config.is_open(datetime(2026, 11, 16, 9, 0, tzinfo=ALMATY))
    assert config.is_open(datetime(2026, 11, 16, 20, 59, tzinfo=ALMATY))
    assert not config.is_open(datetime(2026, 11, 16, 21, 0, tzinfo=ALMATY))
    assert not config.is_open(datetime(2026, 11, 16, 8, 59, tzinfo=ALMATY))
    assert not config.is_open(datetime(2026, 11, 22, 12, 0, tzinfo=ALMATY))
    assert config.is_open(datetime(2026, 11, 16, 5, 0, tzinfo=ZoneInfo("UTC")))


def test_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CRM_ENABLED", raising=False)
    monkeypatch.delenv("BITRIX_WEBHOOK_URL", raising=False)
    settings = Settings(_env_file=None, bot_token="1:token")
    assert settings.crm_enabled is False
    assert settings.client_config == Path("client.yaml")


def test_settings_read_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "1:token")
    monkeypatch.setenv("CRM_ENABLED", "true")
    monkeypatch.setenv("BITRIX_WEBHOOK_URL", "https://example.bitrix24.kz/rest/1/secret/")
    settings = Settings(_env_file=None)
    assert settings.crm_enabled is True
    assert settings.bot_token == "1:token"


def test_settings_require_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_settings_require_webhook_when_crm_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BITRIX_WEBHOOK_URL", raising=False)
    with pytest.raises(ValidationError, match="BITRIX_WEBHOOK_URL"):
        Settings(_env_file=None, bot_token="1:token", crm_enabled=True)


def test_locales_have_identical_keys(translator: Translator) -> None:
    assert translator.keys("ru") == translator.keys("kk")


def test_translator_escapes_values_once(translator: Translator) -> None:
    line = translator.t("ru", "phone_saved", phone="<b>&")
    assert line == "Номер сохранён: &lt;b&gt;&amp;"
    assert isinstance(line, Markup)
    nested = translator.t("ru", "welcome", shop="A&B", welcome=line)
    assert nested.count("&amp;") == 2
    assert "&amp;amp;" not in nested


def test_settings_errors_hide_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BITRIX_WEBHOOK_URL", raising=False)
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, bot_token="1:very-secret-token", crm_enabled=True)
    assert "very-secret-token" not in str(error.value)
