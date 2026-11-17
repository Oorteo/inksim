# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Application-wide opt-in debug logging."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("inksim")
logger.setLevel(logging.DEBUG)
logger.propagate = False
logger.addHandler(logging.NullHandler())
_debug_enabled = False
_file_handler: logging.FileHandler | None = None
_log_path: Path | None = None


def is_enabled() -> bool:
    return _debug_enabled


def configure_logging(
    enabled: bool,
    log_path: str | Path,
    *,
    append: bool = False,
) -> Path | None:
    """Enable file logging for debug diagnostics when requested."""
    global _debug_enabled, _file_handler, _log_path
    if not enabled:
        return None
    path = Path(log_path).expanduser().resolve()
    if _file_handler is not None and _file_handler.stream is not None and _log_path == path:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(path, mode="a" if append else "w", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(created).6f thread=%(thread)d %(message)s"))
    if _file_handler is not None:
        logger.removeHandler(_file_handler)
        _file_handler.close()
    logger.addHandler(handler)
    _file_handler = handler
    _log_path = path
    _debug_enabled = True
    return path
