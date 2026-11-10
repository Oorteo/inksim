# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Path formatting helpers for portable configuration and user-facing text."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def _sanitize_path(path: str | Path) -> str:
    """Return a path string with the user's home directory replaced by '~'."""
    resolved = Path(path).expanduser().resolve()
    home = Path.home()
    try:
        relative = resolved.relative_to(home)
        return f"~/{relative.as_posix()}"
    except ValueError:
        return str(resolved)


def _unsanitize_path(path_str: str) -> str:
    """Expand a portable home-relative path back to the current user's home."""
    if path_str.startswith(("~/", "~\\")):
        return str(Path(path_str).expanduser())
    return path_str


def _sanitize_path_text(text: str) -> str:
    """Replace home-directory path prefixes in text without resolving symlinks."""
    home = Path.home()
    home_forms = {
        str(home),
        home.as_posix(),
        str(home).replace("\\", "/"),
        str(home).replace("/", "\\"),
    }
    for home_form in sorted(home_forms, key=len, reverse=True):
        prefix = rf"(?:^|(?<=[\s\"'=:(,])){re.escape(home_form)}(?=$|[\\/])"
        text = re.sub(prefix, "~", text)
    return text


def _sanitize_config_value(value: Any) -> Any:
    """Recursively replace the current user's home path in TOML-compatible data."""
    if isinstance(value, str):
        return _sanitize_path_text(value)
    if isinstance(value, list):
        return [_sanitize_config_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _sanitize_config_value(item) for key, item in value.items()}
    return value
