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


def link_key(value: str | Path) -> str:
    """Return a comparable key for a path without resolving symlinks.

    Extension folders in Inkscape are often symlinks to a checkout, so the link
    keeps its identity: comparing resolved targets would hide a repointed link.
    """
    return os.path.normcase(os.path.abspath(Path(value).expanduser()))


def _existing_extension_dir(installation: dict[str, Any]) -> Path | None:
    """Return the cached extension directory when it still exists on disk."""
    value = installation.get("extension_dir")
    if not isinstance(value, str) or not value:
        return None
    path = Path(value).expanduser()
    return path if path.is_dir() else None


def changed_inkstitch_targets(status: dict[str, Any]) -> list[Path]:
    """Return checkouts that cached Ink/Stitch links point at but were not stored with.

    Inkscape extension folders are commonly symlinks to a checkout. The stored
    link keeps its identity, so resolving it again tells whether the link was
    repointed to another Ink/Stitch version since the status was cached.
    """
    changed: list[Path] = []
    for installation in status.get("inkstitch") or []:
        if not isinstance(installation, dict):
            continue
        link = installation.get("extension_dir")
        stored = installation.get("resolved_extension_dir")
        if not isinstance(link, str) or not link or not isinstance(stored, str) or not stored:
            continue
        current = Path(link).expanduser().resolve()
        if os.path.normcase(str(current)) != os.path.normcase(str(Path(stored).expanduser())):
            changed.append(current)
    return changed


def missing_inkstitch_links(status: dict[str, Any]) -> list[str]:
    """Return configured extension folders that are no longer there.

    Covers both a removed checkout and a renamed folder in Inkscape's
    extensions directory, because the folder name is part of the link path.
    """
    missing: list[str] = []
    for installation in status.get("inkstitch") or []:
        if not isinstance(installation, dict):
            continue
        link = installation.get("extension_dir")
        if isinstance(link, str) and link and not Path(link).expanduser().is_dir():
            missing.append(link)
    return missing


def active_inkstitch_installation(status: dict[str, Any]) -> dict[str, Any] | None:
    """Return the selected Ink/Stitch installation from cached status.

    A deleted worktree leaves ``active_inkstitch`` pointing at a directory that
    no longer exists, so a single ``is_dir`` check skips the stored choice and
    falls back to an installation that is still there.
    """
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
        active_path = link_key(active_inkstitch)
        for installation in valid_installations:
            if (
                link_key(installation["extension_dir"]) == active_path
                and _existing_extension_dir(installation) is not None
            ):
                return installation
    for installation in valid_installations:
        if _existing_extension_dir(installation) is not None:
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
