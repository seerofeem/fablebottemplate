from __future__ import annotations

import re
from datetime import datetime, time
from pathlib import Path
from typing import Annotated, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SUPPORTED_LANGUAGES = ("ru", "kk")
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
CLOSED = "closed"
HOURS_PATTERN = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)-([01]\d|2[0-3]):([0-5]\d)$")

Identifier = Annotated[str, Field(pattern=r"^[a-z0-9_]{1,32}$")]
Localized = dict[str, str]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", hide_input_in_errors=True
    )

    bot_token: str = Field(min_length=1)
    bitrix_webhook_url: str = ""
    crm_enabled: bool = False
    client_config: Path = Path("client.yaml")
    database_path: Path = Path("data/shop.db")
    assistant_enabled: bool = False
    anthropic_api_key: str = ""
    assistant_model: str = "claude-opus-5-5"
    assistant_daily_limit: int = Field(default=20, ge=1)

    @model_validator(mode="after")
    def check_crm(self) -> Self:
        if self.crm_enabled and not self.bitrix_webhook_url.startswith("https://"):
            raise ValueError("BITRIX_WEBHOOK_URL must be an https URL when CRM_ENABLED is true")
        return self

    @model_validator(mode="after")
    def check_assistant(self) -> Self:
        if self.assistant_enabled and not self.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY must be set when ASSISTANT_ENABLED is true")
        return self


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Shop(StrictModel):
    name: str = Field(min_length=1, max_length=64)
    welcome: Localized
    languages: list[str] = Field(min_length=1)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    timezone: str = "Asia/Almaty"

    @field_validator("languages")
    @classmethod
    def check_languages(cls, value: list[str]) -> list[str]:
        unknown = [code for code in value if code not in SUPPORTED_LANGUAGES]
        if unknown:
            raise ValueError(f"unsupported languages: {', '.join(unknown)}")
        if len(set(value)) != len(value):
            raise ValueError("languages must be unique")
        return value

    @field_validator("timezone")
    @classmethod
    def check_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown timezone: {value}") from exc
        return value


class DeliveryOption(StrictModel):
    id: Identifier
    name: Localized
    price: int = Field(ge=0)
    needs_address: bool = True


class Product(StrictModel):
    id: Identifier
    name: Localized
    price: int = Field(gt=0)
    photo_url: HttpUrl | None = None
    description: Localized


class Category(StrictModel):
    id: Identifier
    name: Localized
    products: list[Product] = Field(min_length=1)


class ClientConfig(StrictModel):
    shop: Shop
    owner_chat_id: int
    working_hours: dict[str, str]
    delivery: list[DeliveryOption] = Field(min_length=1)
    categories: list[Category] = Field(min_length=1)
    faq: list[Localized] = Field(default_factory=list)

    @field_validator("owner_chat_id")
    @classmethod
    def check_owner(cls, value: int) -> int:
        if value == 0:
            raise ValueError("owner_chat_id must be set")
        return value

    @field_validator("working_hours")
    @classmethod
    def check_hours(cls, value: dict[str, str]) -> dict[str, str]:
        if set(value) != set(WEEKDAYS):
            raise ValueError(f"working_hours must have exactly these keys: {', '.join(WEEKDAYS)}")
        for day, hours in value.items():
            if hours == CLOSED:
                continue
            match = HOURS_PATTERN.match(hours)
            if match is None:
                raise ValueError(f"{day}: expected HH:MM-HH:MM or closed, got {hours!r}")
            start, end = parse_hours(hours)
            if start >= end:
                raise ValueError(f"{day}: opening time must be before closing time")
        return value

    @model_validator(mode="after")
    def check_consistency(self) -> Self:
        self._check_unique("delivery", [option.id for option in self.delivery])
        self._check_unique("category", [category.id for category in self.categories])
        self._check_unique("product", [product.id for product in self.products()])
        self._check_localized("shop.welcome", self.shop.welcome)
        for option in self.delivery:
            self._check_localized(f"delivery {option.id} name", option.name)
        for category in self.categories:
            self._check_localized(f"category {category.id} name", category.name)
            for product in category.products:
                self._check_localized(f"product {product.id} name", product.name)
                self._check_localized(f"product {product.id} description", product.description)
        for index, note in enumerate(self.faq, start=1):
            self._check_localized(f"faq item {index}", note)
        return self

    @staticmethod
    def _check_unique(kind: str, ids: list[str]) -> None:
        duplicates = sorted({item for item in ids if ids.count(item) > 1})
        if duplicates:
            raise ValueError(f"duplicate {kind} ids: {', '.join(duplicates)}")

    def _check_localized(self, label: str, value: Localized) -> None:
        missing = [code for code in self.shop.languages if not value.get(code, "").strip()]
        if missing:
            raise ValueError(f"{label}: missing text for languages: {', '.join(missing)}")

    @property
    def default_language(self) -> str:
        return self.shop.languages[0]

    def products(self) -> list[Product]:
        return [product for category in self.categories for product in category.products]

    def product(self, product_id: str) -> Product | None:
        return next((item for item in self.products() if item.id == product_id), None)

    def category(self, category_id: str) -> Category | None:
        return next((item for item in self.categories if item.id == category_id), None)

    def delivery_option(self, delivery_id: str) -> DeliveryOption | None:
        return next((item for item in self.delivery if item.id == delivery_id), None)

    def is_open(self, moment: datetime | None = None) -> bool:
        zone = ZoneInfo(self.shop.timezone)
        local = moment.astimezone(zone) if moment is not None else datetime.now(zone)
        hours = self.working_hours[WEEKDAYS[local.weekday()]]
        if hours == CLOSED:
            return False
        start, end = parse_hours(hours)
        return start <= local.time().replace(second=0, microsecond=0) < end


def parse_hours(value: str) -> tuple[time, time]:
    start, end = value.split("-")
    return time.fromisoformat(start), time.fromisoformat(end)


def pick(value: Localized, language: str) -> str:
    return value.get(language) or next(iter(value.values()))


def load_client_config(path: Path) -> ClientConfig:
    with path.open(encoding="utf-8") as stream:
        raw = yaml.safe_load(stream)
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a YAML mapping at the top level")
    return ClientConfig.model_validate(raw)
