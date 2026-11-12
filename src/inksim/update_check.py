# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Check PyPI for a newer InkSim release.

The check is intentionally lightweight and non-blocking: the caller runs it
on a background thread and only surfaces a result when a newer version is
available.  Network failures are treated as "no update" so a machine without
internet access never shows an error.
"""

from __future__ import annotations

import importlib.metadata
import json
import re
import time
import urllib.request

from PySide6.QtCore import QThread, Signal

from .config import Config

PYPI_JSON_URL = "https://pypi.org/pypi/inksim/json"
REQUEST_TIMEOUT_S = 5.0

# Config keys.
CONFIG_ENABLED = "update_check_enabled"
CONFIG_INTERVAL_DAYS = "update_check_interval_days"
CONFIG_LAST_CHECK = "last_update_check"
CONFIG_LAST_RESULT = "last_update_result"

DEFAULT_INTERVAL_DAYS = 1
_VERSION_PATTERN = re.compile(
    r"^v?(?P<release>\d+(?:\.\d+)*)(?:-?rc\.?(?P<rc>\d+))?$",
    re.IGNORECASE,
)


def current_version() -> str:
    """Return the installed InkSim version, or "0" when unknown."""
    try:
        return importlib.metadata.version("inksim")
    except importlib.metadata.PackageNotFoundError:
        return "0"


def _parse_version(version: str) -> tuple[tuple[int, ...], int, int]:
    """Parse the stable and RC forms produced by the release workflow."""
    match = _VERSION_PATTERN.fullmatch(version)
    if match is None:
        raise ValueError(f"Unsupported InkSim version format: {version!r}")

    release = [int(part) for part in match["release"].split(".")]
    while len(release) > 1 and release[-1] == 0:
        release.pop()

    rc = match["rc"]
    return tuple(release), 0 if rc is not None else 1, int(rc or 0)


def is_newer(latest: str, current: str) -> bool:
    """Return True when *latest* is a newer release than *current*."""
    return _parse_version(latest) > _parse_version(current)


def _latest_stable_version(versions: list[str]) -> str | None:
    """Return the newest stable version, excluding release candidates."""
    stable = [version for version in versions if _parse_version(version)[1] == 1]
    return max(stable, key=_parse_version, default=None)


def fetch_latest_version(timeout: float = REQUEST_TIMEOUT_S) -> str | None:
    """Return the latest published version from PyPI, or None on failure."""
    request = urllib.request.Request(
        PYPI_JSON_URL,
        headers={"User-Agent": "inksim-update-check"},
    )
    try:
        # PYPI_JSON_URL is a hardcoded HTTPS URL, so custom schemes are not a concern.
        with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec B310
            data = json.load(response)
    except (OSError, ValueError):
        return None
    releases = data.get("releases", {})
    if isinstance(releases, dict):
        latest_stable = _latest_stable_version(list(releases))
        if latest_stable is not None:
            return latest_stable

    version = data.get("info", {}).get("version")
    if version and _parse_version(version)[1] == 1:
        return version
    return None


def should_check(config: Config, now: float | None = None) -> bool:
    """Return True when an automatic check is due.

    The check is skipped when disabled, or when the last check happened more
    recently than the configured interval.
    """
    if not config.get(CONFIG_ENABLED, True):
        return False
    now = time.time() if now is None else now
    interval_days = config.get(CONFIG_INTERVAL_DAYS, DEFAULT_INTERVAL_DAYS)
    try:
        interval_days = float(interval_days)
    except (TypeError, ValueError):
        interval_days = DEFAULT_INTERVAL_DAYS
    last = config.get(CONFIG_LAST_CHECK)
    if last is None:
        return True
    try:
        last = float(last)
    except (TypeError, ValueError):
        return True
    return (now - last) >= interval_days * 86400.0


def record_check(config: Config, now: float | None = None) -> None:
    """Persist the timestamp of the most recent check."""
    config.set(CONFIG_LAST_CHECK, time.time() if now is None else now)


def record_result(config: Config, result: str) -> None:
    """Persist the human-readable result of the most recent check."""
    config.set(CONFIG_LAST_RESULT, result)


def last_result(config: Config) -> str:
    """Return the stored result of the most recent check, or ""."""
    return config.get(CONFIG_LAST_RESULT, "") or ""


def last_check_text(config: Config) -> str:
    """Return a human-readable description of the last check, if any."""
    last = config.get(CONFIG_LAST_CHECK)
    if last is None:
        return "never"
    try:
        last = float(last)
    except (TypeError, ValueError):
        return "unknown"
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last))


class UpdateCheckThread(QThread):
    """Fetch the latest version off the GUI thread and report the result."""

    result_ready = Signal(str)  # latest version, or "" when none/error

    def run(self) -> None:  # type: ignore[override]
        latest = fetch_latest_version()
        self.result_ready.emit(latest or "")
