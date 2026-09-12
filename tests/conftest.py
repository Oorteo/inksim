# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import os
from pathlib import Path

import PySide6
import pytest

# Some PySide6 builds omit __version__, which breaks pytest-qt's report header.
if not hasattr(PySide6, "__version__"):
    PySide6.__version__ = "unknown"


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Exit cleanly when all tests passed, skipping the PySide6 shutdown abort.

    PySide6 6.11 aborts during interpreter shutdown when Qt's internal icon /
    style cache constructs a QPixmap after the QApplication has already been
    destroyed (``QPixmap: Must construct a QGuiApplication before a QPixmap``,
    exit code 134 / SIGABRT).  This happens in the C++ layer after every
    atexit handler has run, so it cannot be fixed from test code.

    When the suite is green there is nothing left to report, so we exit the
    process immediately and skip the broken teardown.  On failure we let pytest
    finish normally so the error is reported.
    """
    if exitstatus == 0:
        os._exit(0)


@pytest.fixture(autouse=True)
def _isolate_config(tmp_path, monkeypatch):
    """Redirect the default config path to a temp dir for every test.

    Widgets created without an explicit ``Config`` instance fall back to the
    real user config (``~/.config/inksim/config.toml``), which can contain
    persisted state such as ``active_renderer = "gpu_textured"``.  Restoring
    that state in a headless test would try to show the GL widget and fail.
    Point the default path at a fresh temp file so tests stay isolated.
    """
    import inksim.config as config_module

    monkeypatch.setattr(
        config_module,
        "DEFAULT_CONFIG_PATH",
        tmp_path / "config.toml",
    )


@pytest.fixture
def sample_design():
    """Return an available external embroidery sample by a generic name."""
    sample_directory = Path(__file__).resolve().parent / "data"
    candidates = (
        sample_directory / "sample.csv",
        sample_directory / "sample.pes",
        sample_directory / "square.pes",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    pytest.skip("No external embroidery sample is available")
