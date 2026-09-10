# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Lightweight runtime translation layer for InkSim.

Translations are stored as JSON catalogs under ``src/inksim/locales/``.
Each catalog maps a stable message ID to a translated string.  The English
source text is also stored in the catalog so the source language can be
extracted and updated independently of the translations.

The active locale is read from :class:`~inksim.config.Config` key ``language``,
``LANGUAGE`` / ``LC_ALL`` / ``LANG`` environment variables, and can be changed
while the application is running.  Call :func:`set_active_locale` to switch
language and then trigger a UI retranslate (e.g. ``MainWindow.retranslate_ui()``)
so all visible labels refresh.
"""

from __future__ import annotations

import functools
import json
import os
from pathlib import Path
from typing import Any

from .config import Config

LOCALES_DIR = Path(__file__).with_suffix("").parent / "locales"
DEFAULT_LOCALE = "en"

_current_locale: str | None = None


def _normalize_locale_tag(value: str) -> str:
    """Normalize a locale tag to our internal form.

    ``cs_CZ.UTF-8`` becomes ``cs-CZ``; ``pt_BR`` becomes ``pt-BR``.
    The language subtag is lower-cased, all remaining subtags are upper-cased.
    """
    value = value.strip()
    value = value.split(".")[0]
    value = value.replace("_", "-")
    parts = value.split("-")
    if parts:
        parts[0] = parts[0].lower()
        parts[1:] = [part.upper() for part in parts[1:]]
    return "-".join(parts)


def _locale_chain(locale: str) -> list[str]:
    """Return the language-specific fallback chain for *locale*.

    ``pt-BR`` → ``['pt-BR', 'pt']``. The global ``en`` fallback is added by
    the caller when needed.
    """
    chain = [locale]
    if "-" in locale:
        base = locale.split("-")[0]
        if base != locale and base not in chain:
            chain.append(base)
    return chain


def _resolve_locale(locale: str | None) -> str:
    """Return the best available locale matching *locale*.

    Tries the full tag, then the language-only base, then the default.
    """
    if not locale:
        return DEFAULT_LOCALE
    locale = _normalize_locale_tag(locale)
    available = available_locales()
    for candidate in _locale_chain(locale):
        if candidate in available:
            return candidate
    return DEFAULT_LOCALE if DEFAULT_LOCALE in available else locale


def _environment_locales() -> list[str]:
    """Return locale tags from environment in GNU gettext priority order.

    ``LANGUAGE=cs:sk:de`` yields ``['cs', 'sk', 'de']``; ``LC_ALL`` and ``LANG``
    are appended when present.
    """
    locales: list[str] = []
    language = os.environ.get("LANGUAGE")
    if language:
        locales.extend(tag.strip() for tag in language.split(":") if tag.strip())
    lc_all = os.environ.get("LC_ALL")
    if lc_all:
        locales.append(lc_all)
    lang = os.environ.get("LANG")
    if lang and lang not in locales:
        locales.append(lang)
    return locales


def _resolve_priority_list(locales: list[str]) -> list[str]:
    """Return a normalised, de-duplicated, available priority list.

    For each raw locale the language-specific fallback chain is expanded, so
    ``pt-BR`` also considers ``pt`` before moving to the next priority entry.
    ``en`` is appended only once at the end if it is available and not already
    present.
    """
    available = available_locales()
    seen: set[str] = set()
    resolved: list[str] = []
    for raw in locales:
        normalized = _normalize_locale_tag(raw)
        for candidate in _locale_chain(normalized):
            if candidate in available and candidate not in seen:
                seen.add(candidate)
                resolved.append(candidate)
    if DEFAULT_LOCALE in available and DEFAULT_LOCALE not in seen:
        resolved.append(DEFAULT_LOCALE)
    return resolved


class _TranslationCatalog:
    """Lazy in-memory cache for a single locale catalog.

    The backing JSON file is read only when a translation from this catalog
    is first requested.  This keeps startup fast even when many locale files
    ship with the application.
    """

    __slots__ = ("locale", "_messages", "_meta", "_loaded")

    def __init__(self, locale: str) -> None:
        self.locale = locale
        self._messages: dict[str, str] = {}
        self._meta: dict[str, Any] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        path = LOCALES_DIR / f"{self.locale}.json"
        if not path.exists():
            return
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:  # noqa: BLE001 - a broken locale file is not fatal
            data = {}
        self._meta = data.get("_meta", {})
        for key, value in data.items():
            if key.startswith("_"):
                continue
            if isinstance(value, dict):
                self._messages[key] = value.get("translation", value.get("source", key))
            elif isinstance(value, str):
                self._messages[key] = value
            else:
                self._messages[key] = key

    def gettext(self, message_id: str, default: str | None = None) -> str:
        self._ensure_loaded()
        return self._messages.get(message_id, default if default is not None else message_id)

    def lookup(self, message_id: str) -> str | None:
        """Return the translation if it exists, otherwise None."""
        self._ensure_loaded()
        return self._messages.get(message_id)

    @property
    def language_name(self) -> str:
        self._ensure_loaded()
        return self._meta.get("name", self.locale)


@functools.lru_cache(maxsize=16)
def _catalog(locale: str) -> _TranslationCatalog:
    return _TranslationCatalog(locale)


def available_locales() -> list[str]:
    """Return locale codes for which a catalog file exists."""
    if not LOCALES_DIR.exists():
        return [DEFAULT_LOCALE]
    return sorted(
        p.stem for p in LOCALES_DIR.glob("*.json") if p.stem and not p.stem.startswith("_")
    )


def _active_priority_list() -> list[str]:
    """Return the resolved fallback/priority list used by gettext.

    Resolution order:
    1. Locale explicitly set with :func:`set_active_locale` in this process.
    2. ``language`` value stored in :class:`~inksim.config.Config`.
    3. ``LANGUAGE`` environment variable (colon-separated priority list).
    4. ``LC_ALL`` / ``LANG`` environment variables.
    5. :data:`DEFAULT_LOCALE` (``en``).
    """
    global _current_locale
    candidates: list[str] = []
    if _current_locale is not None:
        candidates.append(_current_locale)
    try:
        locale = Config.load().get("language")
        if locale:
            candidates.append(locale)
    except Exception:  # noqa: BLE001
        pass
    candidates.extend(_environment_locales())
    return _resolve_priority_list(candidates)


def active_locale() -> str:
    """Return the first resolved locale from the priority list."""
    resolved = _active_priority_list()
    return resolved[0] if resolved else DEFAULT_LOCALE


def set_active_locale(locale: str) -> None:
    """Switch the active locale at runtime.

    The resolved locale (with fallback to the language base and then ``en``) is
    persisted to config.  Callers must refresh visible UI text afterwards;
    this function does not touch widgets directly.
    """
    global _current_locale
    locale = _resolve_locale(locale)
    _current_locale = locale
    try:
        cfg = Config.load()
        cfg.set("language", locale)
    except Exception:  # noqa: BLE001
        pass


def get_language_name(locale: str | None = None) -> str:
    """Return the human-readable name for *locale* (or active locale)."""
    locale = locale or active_locale()
    return _catalog(locale).language_name


def gettext(message_id: str, default: str | None = None) -> str:
    """Return the translation for *message_id* using the priority list.

    Walks the full priority list, expanding each locale into its fallback
    chain (e.g. ``pt-BR`` → ``pt`` → ``en``), until a translation is found.
    If the ID is missing everywhere, *default* is returned when provided,
    otherwise the message ID itself.
    """
    for candidate in _active_priority_list():
        result = _catalog(candidate).lookup(message_id)
        if result is not None:
            return result
    return default if default is not None else message_id


_ = gettext


def ngettext(singular_id: str, plural_id: str, n: int, default: str | None = None) -> str:
    """Return *plural_id* when ``n != 1``, otherwise *singular_id*.

    The chosen ID is translated through :func:`gettext`.  A placeholder for
    future plural-form support.
    """
    return gettext(plural_id if n != 1 else singular_id, default)
