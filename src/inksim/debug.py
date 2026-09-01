# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Application-wide opt-in debug logging."""

import logging
from pathlib import Path

logger = logging.getLogger("inksim")
logger.setLevel(logging.DEBUG)
logger.propagate = False
logger.addHandler(logging.NullHandler())
_debug_enabled = False


def is_enabled():
    return _debug_enabled


def configure_logging(enabled, log_path):
    """Enable file logging for debug diagnostics when requested."""
    global _debug_enabled
    if not enabled:
        return None
    path = Path(log_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(created).6f thread=%(thread)d %(message)s")
    )
    logger.addHandler(handler)
    _debug_enabled = True
    return path
