# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Locate the external tools used by the Inkscape/InkStitch integration.

The resolvers are deliberately small and side-effect free so they can be used
from the GUI, from tests, and later from a background worker. Environment
overrides and PATH lookup are handled here; GUI callers can apply the saved
Inkscape executable without changing the environment-based detection.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

INKSCAPE_ENV = "INKSCAPE_EXE"
INKSTITCH_ENV = "INKSTITCH_EXE"
INKSCAPE_CONFIG_KEY = "inkscape"
FLATPAK_LIST_TIMEOUT_S = 5.0
_FLATPAK_STABLE_ID = "org.inkscape.Inkscape"

_PYTHON_ENV_VARS = (
    "VIRTUAL_ENV",
    "PYTHONHOME",
    "PYTHONPATH",
    "PYTHONSTARTUP",
)


def _split_command(value: str) -> list[str]:
    """Split a command line into argv tokens.

    Quotes only group characters; backslashes stay literal so Windows paths
    such as ``C:\\Tools\\inkscape.exe`` survive unchanged.
    """
    tokens: list[str] = []
    current: list[str] = []
    quote: str | None = None
    for character in value:
        if quote is not None:
            if character == quote:
                quote = None
            else:
                current.append(character)
        elif character in "\"'":
            quote = character
        elif character.isspace():
            if current:
                tokens.append("".join(current))
                current = []
        else:
            current.append(character)
    if quote is not None:
        raise ValueError("Unterminated quote in command line")
    if current:
        tokens.append("".join(current))
    return tokens


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
        # without relying on platform-specific tokenization.
        expanded = Path(self.path).expanduser()
        if expanded.is_file():
            return [str(expanded)]
        try:
            return _split_command(self.path)
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
    def can_edit_svg(self) -> bool:
        """Return True when SVG editing can be attempted through Inkscape.

        Ink/Stitch may be installed as an Inkscape extension without a
        standalone ``inkstitch`` command. Direct Ink/Stitch preview uses the
        active extension configuration instead.
        """
        return self.has_inkscape


def normalize_command(command: Sequence[str]) -> tuple[str, ...]:
    """Return a parsed command with the program replaced by an absolute path.

    Comparing two command lines only works once ``inkscape`` and
    ``/usr/bin/inkscape`` normalize alike, and arguments such as
    ``flatpak run org.inkscape.Inkscape`` take part in the comparison.
    """
    program = command[0]
    path = Path(program).expanduser()
    resolved = path.resolve() if path.is_file() else Path(shutil.which(program) or program)
    return (os.path.normcase(str(resolved)), *command[1:])


def configured_command(value: str | None) -> tuple[str, ...]:
    """Return a configured command line as normalized argv tokens."""
    if not isinstance(value, str) or not value.strip():
        return ()
    command = ToolInfo("Inkscape", value, "configuration").command
    if not command:
        return ()
    return normalize_command(command)


def flatpak_inkscape_launchers(timeout: float = FLATPAK_LIST_TIMEOUT_S) -> list[ToolInfo]:
    """Return ``flatpak run <app-id>`` launchers for installed Inkscape builds.

    A Flatpak installation has no Inkscape binary on ``PATH``, and its
    generated launcher only exists in the exports directory, so the app IDs
    reported by Flatpak itself are the reliable source for a usable command.
    """
    executable = shutil.which("flatpak")
    if not executable:
        return []
    try:
        completed = subprocess.run(
            [executable, "list", "--app", "--columns=application"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    app_ids = {line.strip() for line in completed.stdout.splitlines() if "inkscape" in line.lower()}
    ordered = sorted(app_ids, key=lambda app_id: (app_id != _FLATPAK_STABLE_ID, app_id))
    return [
        ToolInfo(name="Inkscape", path=f"flatpak run {app_id}", source="Flatpak")
        for app_id in ordered
        if app_id
    ]


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


def prefer_saved_inkscape(configured_status: object, detected: ToolInfo) -> ToolInfo:
    """Prefer an explicitly saved Inkscape executable over automatic detection."""
    if isinstance(configured_status, dict):
        executable = configured_status.get("executable")
        if isinstance(executable, str) and executable.strip():
            return ToolInfo(name="Inkscape", path=executable, source="configuration")
    return detected


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
