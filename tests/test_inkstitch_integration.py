# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

from inksim.integration.inkstitch import (
    active_inkstitch_installation,
    changed_inkstitch_targets,
    inkstitch_project_python,
    missing_inkstitch_links,
    resolve_inkstitch_preview,
)


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


def _installation(project: Path) -> dict[str, str]:
    return {
        "extension_dir": str(project / "inx"),
        "command": "../inkstitch.py",
        "location": "inx",
        "interpreter": "python",
    }


@pytest.mark.skipif(sys.platform == "win32", reason="symlinked extension folders are POSIX-only")
def test_extension_links_keep_their_identity(tmp_path):
    """The stored extension_dir is the link Inkscape uses, not the checkout it points to."""
    real = _checkout(tmp_path / "checkout")
    extensions = tmp_path / "extensions"
    extensions.mkdir()
    link = extensions / "inkstitch-dev"
    link.symlink_to(real, target_is_directory=True)
    status = {
        "active_inkstitch": str(link / "inx"),
        "inkstitch": [
            {
                **_installation(real),
                "extension_dir": str(link / "inx"),
                "resolved_extension_dir": str((real / "inx").resolve()),
            }
        ],
    }

    installation = active_inkstitch_installation(status)

    assert installation is not None
    assert installation["extension_dir"] == str(link / "inx")
    assert changed_inkstitch_targets(status) == []


@pytest.mark.skipif(sys.platform == "win32", reason="symlinked extension folders are POSIX-only")
def test_repointed_extension_link_is_reported(tmp_path):
    """A link that now points at another checkout is detected without resolving it away."""
    old = _checkout(tmp_path / "old")
    new = _checkout(tmp_path / "new")
    extensions = tmp_path / "extensions"
    extensions.mkdir()
    link = extensions / "inkstitch-dev"
    link.symlink_to(new, target_is_directory=True)
    status = {
        "active_inkstitch": str(link / "inx"),
        "inkstitch": [
            {
                **_installation(old),
                "extension_dir": str(link / "inx"),
                "resolved_extension_dir": str((old / "inx").resolve()),
            }
        ],
    }

    assert changed_inkstitch_targets(status) == [(new / "inx").resolve()]


def test_missing_links_lists_removed_folders(tmp_path):
    """A renamed or removed extension folder is reported, an existing one is not."""
    existing = _checkout(tmp_path / "existing")
    gone = tmp_path / "extensions" / "inkstitch-gone" / "inx"
    status = {
        "inkstitch": [
            {**_installation(existing), "extension_dir": str(existing / "inx")},
            {
                "extension_dir": str(gone),
                "resolved_extension_dir": str(gone),
                "command": "../inkstitch.py",
                "location": "inx",
            },
        ]
    }

    assert missing_inkstitch_links(status) == [str(gone)]


def test_changed_targets_ignores_status_without_a_stored_target(tmp_path):
    status = {"inkstitch": [{"extension_dir": str(tmp_path / "inx")}]}

    assert changed_inkstitch_targets(status) == []


def test_active_installation_skips_a_deleted_worktree(tmp_path):
    """A saved path that no longer exists falls back to an installation that is there."""
    removed = _checkout(tmp_path / "removed")
    kept = _checkout(tmp_path / "kept")
    status = {
        "active_inkstitch": str(removed / "inx"),
        "inkstitch": [_installation(removed), _installation(kept)],
    }
    shutil.rmtree(removed / "inx")

    assert active_inkstitch_installation(status) == _installation(kept)


def test_active_installation_keeps_an_existing_saved_choice(tmp_path):
    first = _checkout(tmp_path / "first")
    second = _checkout(tmp_path / "second")
    status = {
        "active_inkstitch": str(second / "inx"),
        "inkstitch": [_installation(first), _installation(second)],
    }

    assert active_inkstitch_installation(status) == _installation(second)


def test_active_installation_falls_back_to_the_first_entry_when_nothing_exists(tmp_path):
    missing = _installation(tmp_path / "missing")

    assert active_inkstitch_installation({"inkstitch": [missing]}) == missing


def test_preview_returns_none_for_a_deleted_checkout(tmp_path):
    removed = _checkout(tmp_path / "removed")
    status = {
        "active_inkstitch": str(removed / "inx"),
        "inkstitch": [_installation(removed)],
    }
    shutil.rmtree(removed)

    assert resolve_inkstitch_preview(status) is None


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
