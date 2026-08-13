from pathlib import Path

import pytest


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
