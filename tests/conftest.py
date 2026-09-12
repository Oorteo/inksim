# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import atexit
import gc
from pathlib import Path

import PySide6
import pytest
from PySide6.QtWidgets import QApplication

# Some PySide6 builds omit __version__, which breaks pytest-qt's report header.
if not hasattr(PySide6, "__version__"):
    PySide6.__version__ = "unknown"


def _finalize_qt_objects() -> None:
    """Release every remaining Qt object while the QApplication is still alive.

    Some widgets hold QPixmap/QImage objects that are only freed when Python's
    garbage collector runs.  If the QApplication is torn down first (which
    happens at interpreter shutdown), that finalization aborts with
    ``QPixmap: Must construct a QGuiApplication before a QPixmap``.

    This runs via ``atexit`` so it fires after pytest and pytest-qt have fully
    finished, but before the interpreter destroys the QApplication.
    """
    app = QApplication.instance()
    if app is None:
        return
    app.closeAllWindows()
    app.processEvents()
    # Collect cycles so Qt objects are finalized while the app still exists.
    gc.collect()
    app.processEvents()


atexit.register(_finalize_qt_objects)


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
