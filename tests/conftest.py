# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import Path
import PySide6
import pytest

# Some PySide6 builds omit __version__, which breaks pytest-qt's report header.
if not hasattr(PySide6, "__version__"):
    PySide6.__version__ = "unknown"


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
