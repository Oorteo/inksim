# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Runtime information shared by the CLI and the About dialog."""

import importlib.metadata
import os
import platform
import sys
from pathlib import Path

from .constants import APP_TITLE


def _sanitize_path(path):
    """Return a path string with the user's home directory replaced by '~'."""
    path = Path(path).resolve()
    home = Path.home()
    try:
        relative = path.relative_to(home)
        return f"~/{relative.as_posix()}"
    except ValueError:
        return str(path)


def _unsanitize_path(path_str):
    """Expand a '~' prefix back to the user's home directory."""
    if path_str.startswith("~/"):
        return str(Path.home() / path_str[2:])
    return path_str


def is_opengl33_available():
    """Return True if an OpenGL 3.3 Core Profile context can be created.

    This is used to decide whether the GPU textured stitch renderer can be
    enabled. VirtualBox and older graphics drivers often only expose OpenGL
    3.0 or lower, in which case the raster-based CPU renderers are used as a
    fallback.
    """
    from PySide6.QtGui import QOffscreenSurface, QOpenGLContext, QSurfaceFormat
    from PySide6.QtWidgets import QApplication

    if QApplication.instance() is None:
        # A QApplication is required for OpenGL context creation. When the
        # function is called before the GUI is up, report unavailable.
        return False

    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)

    ctx = QOpenGLContext()
    ctx.setFormat(fmt)
    if not ctx.create():
        return False

    surface = QOffscreenSurface()
    surface.setFormat(fmt)
    surface.create()
    if not surface.isValid():
        return False

    if not ctx.makeCurrent(surface):
        return False

    try:
        version = ctx.format()
        available = version.majorVersion() > 3 or (
            version.majorVersion() == 3 and version.minorVersion() >= 3
        )
    finally:
        ctx.doneCurrent()

    return available


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
        f"package: {_sanitize_path(package_path)}",
        f"python: {platform.python_version()}",
        f"executable: {_sanitize_path(Path(sys.executable).resolve())}",
        f"environment: {_sanitize_path(environment) if environment != 'none' else environment}",
        f"cwd: {_sanitize_path(Path.cwd())}",
        f"PySide6: {pyside_version}",
        f"Qt: {qVersion()}",
        f"NumPy: {numpy.__version__}",
        f"Numba: {numba.__version__}",
        f"pystitch: {pystitch_version}",
    )