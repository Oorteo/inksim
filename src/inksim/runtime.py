"""Runtime information shared by the CLI and the About dialog."""

import importlib.metadata
import os
import platform
import sys
from pathlib import Path

from .constants import APP_TITLE


def runtime_info_lines():
    """Return human-readable package and dependency runtime information."""
    package_path = Path(__file__).resolve().parent
    project_root = package_path.parent.parent
    is_development = (project_root / "pyproject.toml").is_file()
    try:
        package_version = importlib.metadata.version("inksim")
    except importlib.metadata.PackageNotFoundError:
        package_version = "unknown"

    import numba
    import numpy
    import pystitch
    import PySide6
    from PySide6.QtCore import qVersion

    pyside_version = getattr(PySide6, "__version__", "unknown")

    virtual_env = os.environ.get("VIRTUAL_ENV")
    environment = virtual_env or (
        sys.prefix if sys.prefix != sys.base_prefix else "none"
    )
    try:
        pystitch_version = importlib.metadata.version("pystitch")
    except importlib.metadata.PackageNotFoundError:
        pystitch_version = "unknown"

    return (
        f"{APP_TITLE} {package_version}",
        f"mode: {'development/editable' if is_development else 'installed package'}",
        f"package: {package_path}",
        f"python: {platform.python_version()}",
        f"executable: {Path(sys.executable).resolve()}",
        f"environment: {environment}",
        f"cwd: {Path.cwd()}",
        f"PySide6: {pyside_version}",
        f"Qt: {qVersion()}",
        f"NumPy: {numpy.__version__}",
        f"Numba: {numba.__version__}",
        f"pystitch: {pystitch_version}",
    )