# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Lightweight runtime translation layer for InkSim.

Translations are stored as JSON catalogs under ``src/inksim/locales/``.
Each catalog maps a stable message ID to a translated string.  The English
source text is also stored in the catalog so the source language can be
extracted and updated independently of the translations.

The active locale is read from :class:`~inksim.config.Config` key ``language``
and can be changed while the application is running.  Call
:func:`set_active_locale` to switch language and then trigger a UI retranslate
(e.g. ``MainWindow.retranslate_ui()``) so all visible labels refresh.
"""

from __future__ import annotations

import functools
import json
from pathlib import Path
from typing import Any

from .config import Config

LOCALES_DIR = Path(__file__).with_suffix("").parent / "locales"
DEFAULT_LOCALE = "en"

_current_locale: str | None = None


class _TranslationCatalog:
    """In-memory cache for a single locale catalog."""

    __slots__ = ("locale", "_messages", "_meta")

    def __init__(self, locale: str) -> None:
        self.locale = locale
        self._messages: dict[str, str] = {}
        self._meta: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
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
        return self._messages.get(message_id, default if default is not None else message_id)

    @property
    def language_name(self) -> str:
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


def active_locale() -> str:
    """Return the currently active locale code."""
    global _current_locale
    if _current_locale is not None:
        return _current_locale
    try:
        locale = Config.load().get("language", DEFAULT_LOCALE)
    except Exception:  # noqa: BLE001
        locale = DEFAULT_LOCALE
    if locale not in available_locales():
        locale = DEFAULT_LOCALE
    _current_locale = locale
    return _current_locale


def set_active_locale(locale: str) -> None:
    """Switch the active locale at runtime.

    The change is persisted to config.  Callers must refresh visible UI text
    afterwards; this function does not touch widgets directly.
    """
    global _current_locale
    locale = locale if locale in available_locales() else DEFAULT_LOCALE
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
    """Return the translation for *message_id* in the active locale.

    If the ID is missing, *default* is returned when provided, otherwise the
    message ID itself is returned untranslated.  This makes it safe to use
    before all catalogs are complete.
    """
    return _catalog(active_locale()).gettext(message_id, default)


_ = gettext


def ngettext(singular_id: str, plural_id: str, n: int, default: str | None = None) -> str:
    """Return *plural_id* when ``n != 1``, otherwise *singular_id*.

    The chosen ID is translated through :func:`gettext`.  A placeholder for
    future plural-form support.
    """
    return gettext(plural_id if n != 1 else singular_id, default)
