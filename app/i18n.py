from __future__ import annotations

import html
from pathlib import Path

import yaml

LOCALES_DIR = Path(__file__).resolve().parent.parent / "locales"


class Markup(str):
    __slots__ = ()


def escape(value: object) -> str:
    if isinstance(value, Markup):
        return value
    return html.escape(str(value), quote=False)


def join_lines(parts: list[Markup]) -> Markup:
    return Markup("\n".join(parts))


class Translator:
    def __init__(self, catalogs: dict[str, dict[str, str]], default: str) -> None:
        if default not in catalogs:
            raise ValueError(f"no locale file for default language {default}")
        self._catalogs = catalogs
        self._default = default

    @property
    def languages(self) -> tuple[str, ...]:
        return tuple(self._catalogs)

    def keys(self, language: str) -> set[str]:
        return set(self._catalogs[language])

    def _template(self, language: str, key: str) -> str:
        catalog = self._catalogs.get(language, self._catalogs[self._default])
        return catalog.get(key) or self._catalogs[self._default][key]

    def t(self, language: str, key: str, **values: object) -> Markup:
        escaped = {name: escape(value) for name, value in values.items()}
        return Markup(self._template(language, key).format(**escaped))

    def plain(self, language: str, key: str, **values: object) -> str:
        return self._template(language, key).format(**values)


def load_translator(languages: list[str], directory: Path = LOCALES_DIR) -> Translator:
    catalogs: dict[str, dict[str, str]] = {}
    for code in languages:
        path = directory / f"{code}.yaml"
        with path.open(encoding="utf-8") as stream:
            raw = yaml.safe_load(stream)
        if not isinstance(raw, dict):
            raise ValueError(f"{path}: expected a YAML mapping")
        catalogs[code] = {str(key): str(value) for key, value in raw.items()}
    return Translator(catalogs, languages[0])
