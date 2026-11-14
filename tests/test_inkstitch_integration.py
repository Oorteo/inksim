# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from inksim.integration.inkstitch import inkstitch_project_python, resolve_inkstitch_preview


def _checkout(tmp_path: Path, *, virtualenv: bool = True) -> Path:
    """Create a source Ink/Stitch layout with an `inx` directory and a virtualenv."""
    project = tmp_path / "inkstitch"
    (project / "inx").mkdir(parents=True)
    (project / "inkstitch.py").write_text("# Ink/Stitch test script\n", encoding="utf-8")
    if virtualenv:
        directory = "Scripts" if sys.platform == "win32" else "bin"
        executable = "python.exe" if sys.platform == "win32" else "python"
        venv_bin = project / ".venv" / directory
        venv_bin.mkdir(parents=True)
        (venv_bin / executable).write_text("", encoding="utf-8")
    return project


def _project_python(project: Path) -> Path:
    directory = "Scripts" if sys.platform == "win32" else "bin"
    executable = "python.exe" if sys.platform == "win32" else "python"
    return project / ".venv" / directory / executable


@pytest.mark.skipif(sys.platform == "win32", reason="symlinked virtualenvs are POSIX-only")
def test_project_python_keeps_the_virtualenv_path(tmp_path):
    """Never resolve the venv away to the base interpreter from the uv installation."""
    project = _checkout(tmp_path)
    base_python = tmp_path / "uv" / "python" / "python3.13"
    base_python.parent.mkdir(parents=True)
    base_python.write_text("", encoding="utf-8")
    interpreter = _project_python(project)
    interpreter.unlink()
    interpreter.symlink_to(base_python)

    assert inkstitch_project_python(project / "inkstitch.py") == interpreter
    assert inkstitch_project_python(project / "inkstitch.py") != interpreter.resolve()


def test_project_python_is_none_without_a_virtualenv(tmp_path):
    project = _checkout(tmp_path, virtualenv=False)

    assert inkstitch_project_python(project / "inkstitch.py") is None


def test_preview_prefers_the_checkout_interpreter_over_a_stale_preference(tmp_path):
    """Bind the interpreter to the Ink/Stitch checkout instead of Inkscape's stale setting."""
    project = _checkout(tmp_path)
    stale_python = tmp_path / "stale" / "python"
    stale_python.parent.mkdir()
    stale_python.write_text("", encoding="utf-8")
    status = {
        "active_inkstitch": str(project / "inx"),
        "inkstitch": [
            {
                "extension_dir": str(project / "inx"),
                "command": "../inkstitch.py",
                "location": "inx",
                "interpreter": "python",
            }
        ],
        "python-interpretor": str(stale_python),
    }

    resolved = resolve_inkstitch_preview(status)

    assert resolved == (
        (project / "inkstitch.py").resolve(),
        _project_python(project),
        (project / "inx").resolve(),
    )


def test_preview_uses_the_configured_interpreter_without_a_checkout_virtualenv(tmp_path):
    project = _checkout(tmp_path, virtualenv=False)
    configured_python = tmp_path / "configured" / "python"
    configured_python.parent.mkdir()
    configured_python.write_text("", encoding="utf-8")
    status = {
        "active_inkstitch": str(project / "inx"),
        "inkstitch": [
            {
                "extension_dir": str(project / "inx"),
                "command": "../inkstitch.py",
                "location": "inx",
                "interpreter": "python",
            }
        ],
        "python-interpretor": str(configured_python),
    }

    resolved = resolve_inkstitch_preview(status)

    assert resolved == (
        (project / "inkstitch.py").resolve(),
        configured_python,
        (project / "inx").resolve(),
    )


def test_preview_runs_frozen_builds_without_an_interpreter(tmp_path):
    """Frozen Ink/Stitch ships its own executable, so no Python preference is needed."""
    project = _checkout(tmp_path, virtualenv=False)
    bundled = project / "bin" / "inkstitch"
    bundled.parent.mkdir()
    bundled.write_text("", encoding="utf-8")
    status = {
        "active_inkstitch": str(project / "inx"),
        "inkstitch": [
            {
                "extension_dir": str(project / "inx"),
                "command": "../bin/inkstitch",
                "location": "inx",
            }
        ],
    }

    resolved = resolve_inkstitch_preview(status)

    assert resolved == (
        (project / "bin" / "inkstitch").resolve(),
        None,
        (project / "inx").resolve(),
    )
