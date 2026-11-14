# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Resolve the active Ink/Stitch extension and its subprocess environment."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from .paths import clean_child_environment


def inkstitch_project_python(script_path: Path) -> Path | None:
    """Return the virtualenv interpreter of the Ink/Stitch checkout holding *script_path*.

    The returned path deliberately keeps the ``.venv`` component: resolving the
    usual ``bin/python`` symlink would yield the base interpreter from the uv
    (or system) installation and silently drop the project's site-packages.
    """
    directory = "Scripts" if sys.platform == "win32" else "bin"
    executable = "python.exe" if sys.platform == "win32" else "python"
    for project in (script_path.parent, script_path.parent.parent):
        candidate = project / ".venv" / directory / executable
        if candidate.is_file():
            return candidate
    return None


def _configured_python(status: dict[str, Any]) -> Path | None:
    """Return the interpreter configured in Inkscape preferences when it exists."""
    configured = status.get("python-interpretor")
    if not isinstance(configured, str) or not configured:
        return None
    path = Path(configured).expanduser()
    return path if path.is_file() else None


def active_inkstitch_installation(status: dict[str, Any]) -> dict[str, Any] | None:
    """Return the selected Ink/Stitch extension installation from cached status."""
    installations = status.get("inkstitch")
    if not isinstance(installations, list):
        return None
    valid_installations = [
        installation
        for installation in installations
        if isinstance(installation, dict) and isinstance(installation.get("extension_dir"), str)
    ]
    if not valid_installations:
        return None
    active_inkstitch = status.get("active_inkstitch")
    if isinstance(active_inkstitch, str):
        active_path = os.path.normcase(str(Path(active_inkstitch).expanduser().resolve()))
        for installation in valid_installations:
            extension_dir = os.path.normcase(
                str(Path(installation["extension_dir"]).expanduser().resolve())
            )
            if extension_dir == active_path:
                return installation
    return valid_installations[0]


def resolve_inkstitch_preview(
    status: dict[str, Any],
) -> tuple[Path, Path | None, Path] | None:
    """Return the active Ink/Stitch script, optional interpreter, and extension folder."""
    installation = active_inkstitch_installation(status)
    if installation is None:
        return None
    command = installation.get("command")
    if not isinstance(command, str) or not command:
        return None
    script_path = Path(command).expanduser()
    if installation.get("location") == "inx" and not script_path.is_absolute():
        script_path = Path(installation["extension_dir"]).expanduser() / script_path
    script_path = script_path.resolve()
    if not script_path.is_file():
        return None
    extension_dir = Path(installation["extension_dir"]).expanduser().resolve()
    if (
        isinstance(installation.get("interpreter"), str)
        and installation["interpreter"].lower() == "python"
    ):
        python_path = inkstitch_project_python(script_path) or _configured_python(status)
        if python_path is None:
            return None
        return script_path, python_path, extension_dir
    return script_path, None, extension_dir


def inkstitch_process_environment(
    extension_dir: Path, status: dict[str, Any] | None
) -> dict[str, str]:
    """Build the clean process environment needed by Ink/Stitch."""
    environment = clean_child_environment()
    environment["INKSTITCH_OFFLINE_SCRIPT"] = "True"
    environment["INKEX_GETTEXT_DOMAIN"] = "inkstitch"
    environment["DOCUMENT_PATH"] = ""

    gettext_directory = extension_dir / "locale"
    if gettext_directory.is_dir():
        environment["INKEX_GETTEXT_DIRECTORY"] = str(gettext_directory)

    preferences_file = status.get("preferences_file") if status is not None else None
    if isinstance(preferences_file, str):
        environment["INKSCAPE_PROFILE_DIR"] = str(
            Path(preferences_file).expanduser().resolve().parent
        )
    return environment
