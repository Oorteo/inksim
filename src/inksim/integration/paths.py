# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Locate the external tools used by the Inkscape/InkStitch integration.

The resolvers are deliberately small and side-effect free so they can be used
from the GUI, from tests, and later from a background worker.  Configuration
and version probing will be added in a later step; this module currently
supports the environment overrides and executable lookup needed by the new
open dialog.
"""

from __future__ import annotations

import os
import shlex
import shutil
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

INKSCAPE_ENV = "INKSCAPE_EXE"
INKSTITCH_ENV = "INKSTITCH_EXE"
INKSCAPE_CONFIG_KEY = "inkscape"

_PYTHON_ENV_VARS = (
    "VIRTUAL_ENV",
    "PYTHONHOME",
    "PYTHONPATH",
    "PYTHONSTARTUP",
)


@dataclass(frozen=True)
class ToolInfo:
    """A discovered external tool.

    ``path`` is the configured command line or the executable found on
    ``PATH``.  It may contain arguments for tools such as Ink/Stitch, so use
    :attr:`command` instead of treating it as a plain path.
    """

    name: str
    path: str | None
    source: str

    @property
    def found(self) -> bool:
        """Return True when a command line was configured or discovered."""
        return bool(self.path)

    @property
    def command(self) -> list[str]:
        """Return the configured command line split into argv tokens."""
        if not self.path:
            return []
        # A plain path may contain spaces; prefer it as a single program when
        # it points at an existing file.  This also covers quoted Windows paths
        # without requiring shlex platform quirks.
        expanded = Path(self.path).expanduser()
        if expanded.is_file():
            return [str(expanded)]
        try:
            return shlex.split(self.path, posix=os.name != "nt")
        except ValueError:
            return [self.path]


@dataclass(frozen=True)
class ToolStatus:
    """The tools needed for the SVG preview and editing workflow."""

    inkscape: ToolInfo
    inkstitch: ToolInfo

    @property
    def has_inkscape(self) -> bool:
        return self.inkscape.found

    @property
    def has_inkstitch(self) -> bool:
        return self.inkstitch.found

    @property
    def can_preview_svg(self) -> bool:
        """Return True when the Inkscape export backend can be attempted.

        Ink/Stitch may be installed as an Inkscape extension without a
        standalone ``inkstitch`` command, so the absence of the standalone
        command does not disable the preview.  The conversion itself reports a
        useful error when Ink/Stitch is missing inside Inkscape.
        """
        return self.has_inkscape


def _from_environment(name: str, variable: str) -> ToolInfo | None:
    value = os.environ.get(variable, "").strip()
    if not value:
        return None
    return ToolInfo(name=name, path=value, source="environment")


def _from_path(name: str, executable: str) -> ToolInfo:
    path = shutil.which(executable)
    return ToolInfo(name=name, path=path, source="PATH" if path else "missing")


def detect_tools() -> ToolStatus:
    """Return the currently available Inkscape and Ink/Stitch commands."""
    inkscape = _from_environment("Inkscape", INKSCAPE_ENV) or _from_path("Inkscape", "inkscape")
    inkstitch = _from_environment("Ink/Stitch", INKSTITCH_ENV) or _from_path(
        "Ink/Stitch", "inkstitch"
    )
    return ToolStatus(inkscape=inkscape, inkstitch=inkstitch)


def build_inkscape_export_arguments(
    command: Sequence[str],
    svg_path: Path,
    csv_path: Path,
) -> list[str]:
    """Build the argv used to export an SVG to CSV through Inkscape.

    The first element is the program; callers using ``QProcess`` should split
    the result into program and arguments.
    """
    return [
        *command,
        "--batch-process",
        "--export-type=csv",
        f"--export-filename={csv_path}",
        str(svg_path),
    ]


def clean_child_environment() -> dict[str, str]:
    """Return an environment suitable for launching Inkscape.

    InkSim often runs inside a virtual environment created by ``uv`` or
    ``venv``.  Inkscape executes its extensions with a ``python`` interpreter
    from ``PATH``; if the InkSim environment leaks into that process, the
    Ink/Stitch extension can load the wrong Python or the wrong packages and
    hang.  Strip the active Python environment and remove its ``bin`` /
    ``Scripts`` directory from ``PATH`` while keeping the rest of the
    environment intact.
    """
    environment = dict(os.environ)
    for key in _PYTHON_ENV_VARS:
        environment.pop(key, None)

    prefixes: set[Path] = set()
    virtual_env = os.environ.get("VIRTUAL_ENV")
    if virtual_env:
        prefixes.add(Path(virtual_env))
    if sys.prefix != sys.base_prefix:
        prefixes.add(Path(sys.prefix))
    if prefixes:
        venv_paths = {
            _normalized_path(path)
            for prefix in prefixes
            for path in (prefix, prefix / "bin", prefix / "Scripts")
        }
        parts = environment.get("PATH", "").split(os.pathsep)
        environment["PATH"] = os.pathsep.join(
            part
            for part in parts
            if part and _normalized_path(Path(part.strip('"'))) not in venv_paths
        )
    return environment


def _normalized_path(path: Path) -> str:
    try:
        resolved = path.expanduser().resolve()
    except OSError:
        resolved = Path(os.path.abspath(str(path)))
    return os.path.normcase(str(resolved))
