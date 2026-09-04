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
from pathlib import Path
from typing import Any

import tomli_w
from filelock import FileLock, Timeout


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
        self._load()

    def _load(self) -> None:
        """Read the TOML file from disk, creating defaults if missing."""
        if not self.path.is_file():
            self._data = {}
            return
        import tomllib

        try:
            with self.path.open("rb") as f:
                self._data = tomllib.load(f)
        except Exception:  # noqa: BLE001 - corrupt config is not fatal
            self._data = {}

    def reload(self) -> None:
        """Reload the on-disk TOML file into this instance."""
        self._load()

    def _save_locked(self) -> None:
        """Write the in-memory data atomically to ``self.path``."""
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
        """Persist the current in-memory data atomically.

        Args:
            timeout: Seconds to wait for the file lock. Raises ``Timeout``
                if the lock cannot be acquired.
        """
        with self._lock.acquire(timeout=timeout):
            # Re-read before writing so concurrent edits are less likely to be
            # overwritten blindly, then merge our current values on top.
            old_data = dict(self._data)
            self._load()
            self._data.update(old_data)
            self._save_locked()

    def get(self, key: str, default: Any = None) -> Any:
        """Return the value for *key*, or *default* if it is not set."""
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set *key* to *value* and persist the file."""
        self._data[key] = value
        self.save()

    def delete(self, key: str) -> None:
        """Remove *key* from the config and persist the file."""
        self._data.pop(key, None)
        self.save()

    def set_values(self, values: dict[str, Any]) -> None:
        """Update several top-level keys at once and persist once."""
        self._data.update(values)
        self.save()

    def update(self, key: str, updater: "callable") -> None:
        """Read *key*, apply *updater* under the file lock, and persist.

        This guarantees an atomic read-modify-write for a single key across
        concurrent InkSim instances. The callable receives the current value
        (or ``None`` if absent) and must return the new value.
        """
        with self._lock.acquire(timeout=5.0):
            self._load()
            old_value = self._data.get(key)
            self._data[key] = updater(old_value)
            self._save_locked()

    def as_text(self) -> str:
        """Return the current data as a TOML-formatted string."""
        return tomli_w.dumps(self._data)

    def load_text(self, text: str) -> None:
        """Replace the in-memory data with *text* and persist it.

        Raises:
            ValueError: If *text* is not valid TOML.
        """
        import tomllib

        try:
            self._data = tomllib.loads(text)
        except Exception as exc:
            raise ValueError(f"Invalid TOML: {exc}") from exc
        self.save()

    def merge_data(self, data: dict[str, Any]) -> None:
        """Merge *data* into the current in-memory dictionary and persist.

        Unlike :meth:`set_values`, this recursively merges nested dictionaries
        so existing sibling keys are preserved.
        """
        self._data = self._merge(self._data, data)
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
