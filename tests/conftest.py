# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import gc
from pathlib import Path

import PySide6
import pytest
from PySide6.QtWidgets import QApplication

# Some PySide6 builds omit __version__, which breaks pytest-qt's report header.
if not hasattr(PySide6, "__version__"):
    PySide6.__version__ = "unknown"


@pytest.fixture(autouse=True, scope="session")
def _cleanup_qt_on_session_end():
    """Force pending Qt cleanup before the session QApplication exits.

    Some widgets hold Pixmaps that are freed only at Python garbage-collection
    time.  If the QApplication is destroyed first, that finalization aborts.
    Close all windows, pump the event loop and collect garbage while the app is
    still alive.
    """
    yield
    app = QApplication.instance()
    if app is not None:
        app.closeAllWindows()
        app.processEvents()
        gc.collect()
        app.processEvents()


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
