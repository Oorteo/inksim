# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

"""TOML-backed application configuration for InkSim.

Replaces the previous QSettings/INI storage with a single user TOML file.
Writes are atomic (temp file + os.replace) and guarded by a file lock so
concurrent InkSim instances do not corrupt the file.
"""

from __future__ import annotations

import os
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import tomli_w
from filelock import FileLock

from .paths import _sanitize_config_value


def _default_config_dir() -> Path:
    """Return the per-user configuration directory.

    Uses XDG_CONFIG_HOME on Unix-like platforms; falls back to a
    platform-specific user data directory on other systems.
    """
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "InkSim"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Preferences" / "inksim"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "inksim"
    return Path.home() / ".config" / "inksim"


DEFAULT_CONFIG_PATH = _default_config_dir() / "config.toml"


class Config:
    """Persistent key/value store backed by a TOML file.

    Values are stored in a nested dictionary mirroring the TOML document.
    Top-level keys can be read/written via :meth:`get` / :meth:`set`.
    """

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path or DEFAULT_CONFIG_PATH)
        self._lock_path = Path(str(self.path) + ".lock")
        self._lock = FileLock(str(self._lock_path))
        self._data: dict[str, Any] = {}
        self._pending: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        """Read the TOML file and sanitize values in memory without persisting."""
        import tomllib

        try:
            config_file = self.path.open("rb")
        except FileNotFoundError:
            self._data = {}
            return

        try:
            with config_file as f:
                loaded = tomllib.load(f)
        except (tomllib.TOMLDecodeError, UnicodeDecodeError):
            self._data = {}
            return
        self._data = _sanitize_config_value(loaded)

    def reload(self) -> None:
        """Reload the on-disk TOML file into this instance."""
        self._load()

    def _save_locked(self) -> None:
        """Write the in-memory data atomically to ``self.path``."""
        self._data = _sanitize_config_value(self._data)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            suffix=".tmp",
            prefix=self.path.name + ".",
            dir=str(self.path.parent),
        )
        os.close(fd)
        try:
            with open(tmp_name, "wb") as f:
                tomli_w.dump(self._data, f)
            os.replace(tmp_name, self.path)
        except Exception:
            try:
                Path(tmp_name).unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def save(self, timeout: float = 5.0) -> None:
        """Persist the values this instance changed, atomically.

        The file is re-read first and only the keys changed through this
        instance are applied on top. Merging the whole in-memory snapshot would
        let a long-lived instance (the main window) roll back newer values
        written by a short-lived one (the open dialog remembering its view).

        Args:
            timeout: Seconds to wait for the file lock. Raises ``Timeout``
                if the lock cannot be acquired.
        """
        with self._lock.acquire(timeout=timeout):
            pending = dict(self._pending)
            self._load()
            if pending:
                self._data.update(pending)
            self._save_locked()
            self._pending.clear()

    def get(self, key: str, default: Any = None) -> Any:
        """Return the value for *key*, or *default* if it is not set."""
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set *key* to *value* and persist the file."""
        self._data[key] = value
        self._pending[key] = value
        self.save()

    def delete(self, key: str) -> None:
        """Remove *key* from the config and persist the file.

        Writes directly under the lock (re-reading first) rather than going
        through :meth:`save`, whose merge step would re-introduce the deleted
        key from the on-disk copy.
        """
        with self._lock.acquire(timeout=5.0):
            self._pending.pop(key, None)
            self._load()
            self._data.pop(key, None)
            self._save_locked()

    def set_values(self, values: dict[str, Any]) -> None:
        """Update several top-level keys at once and persist once."""
        self._data.update(values)
        self._pending.update(values)
        self.save()

    def update(self, key: str, updater: Callable[[Any], Any]) -> None:
        """Read *key*, apply *updater* under the file lock, and persist.

        This guarantees an atomic read-modify-write for a single key across
        concurrent InkSim instances. The callable receives the current value
        (or ``None`` if absent) and must return the new value.
        """
        with self._lock.acquire(timeout=5.0):
            self._pending.pop(key, None)
            self._load()
            old_value = self._data.get(key)
            self._data[key] = updater(old_value)
            self._save_locked()

    def as_text(self) -> str:
        """Return the current data as a TOML-formatted string."""
        return tomli_w.dumps(_sanitize_config_value(self._data))

    def load_text(self, text: str) -> None:
        """Replace the in-memory data with *text* and persist it.

        This is a full replacement: keys removed from *text* are deleted from
        the file, unlike :meth:`save` which merges with the on-disk content.

        Raises:
            ValueError: If *text* is not valid TOML.
        """
        import tomllib

        try:
            self._data = _sanitize_config_value(tomllib.loads(text))
        except Exception as exc:
            raise ValueError(f"Invalid TOML: {exc}") from exc
        self._pending.clear()
        with self._lock.acquire(timeout=5.0):
            self._save_locked()

    def merge_data(self, data: dict[str, Any]) -> None:
        """Merge *data* into the current in-memory dictionary and persist.

        Unlike :meth:`set_values`, this recursively merges nested dictionaries
        so existing sibling keys are preserved.
        """
        self._data = self._merge(self._data, data)
        self._pending.update({key: self._data[key] for key in data if key in self._data})
        self.save()

    @staticmethod
    def _merge(base: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
        """Recursively merge *update* into *base*."""
        result = dict(base)
        for key, value in update.items():
            if isinstance(value, dict) and isinstance(result.get(key), dict):
                result[key] = Config._merge(result[key], value)
            else:
                result[key] = value
        return result
