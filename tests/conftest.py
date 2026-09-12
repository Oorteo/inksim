# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import Path

import PySide6
import pytest

# Some PySide6 builds omit __version__, which breaks pytest-qt's report header.
if not hasattr(PySide6, "__version__"):
    PySide6.__version__ = "unknown"


@pytest.fixture(scope="session")
def qapp():
    """Create a single QApplication that lives for the whole test session.

    The default pytest-qt fixture destroys the application after each test,
    which can crash if any deferred GUI objects (timers, pixmaps) are still
    being finalized.  Keeping one application alive avoids those shutdown
    aborts in headless CI runs.
    """
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app
    # Do not explicitly destroy the application; let the process exit handle it.


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
