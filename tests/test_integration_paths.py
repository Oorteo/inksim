# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

import os
from pathlib import Path

from inksim.integration.paths import (
    ToolInfo,
    ToolStatus,
    build_inkscape_export_arguments,
    clean_child_environment,
    detect_tools,
)


def _clear_tool_environment(monkeypatch) -> None:
    monkeypatch.delenv("INKSCAPE_EXE", raising=False)
    monkeypatch.delenv("INKSTITCH_EXE", raising=False)


def test_environment_overrides_take_precedence(monkeypatch):
    monkeypatch.setenv("INKSCAPE_EXE", "/custom/inkscape")
    monkeypatch.setenv(
        "INKSTITCH_EXE",
        "uv run --project /tmp/inkstitch python inkstitch.py",
    )

    status = detect_tools()

    assert status.inkscape.path == "/custom/inkscape"
    assert status.inkscape.source == "environment"
    assert status.inkstitch.command == [
        "uv",
        "run",
        "--project",
        "/tmp/inkstitch",
        "python",
        "inkstitch.py",
    ]


def test_path_lookup_is_used_when_environment_is_empty(monkeypatch):
    _clear_tool_environment(monkeypatch)
    monkeypatch.setattr(
        "inksim.integration.paths.shutil.which",
        lambda name: f"/usr/bin/{name}" if name == "inkscape" else None,
    )

    status = detect_tools()

    assert status.inkscape.path == "/usr/bin/inkscape"
    assert status.inkscape.source == "PATH"
    assert status.inkstitch.path is None
    assert status.inkstitch.source == "missing"


def test_missing_tools_are_reported(monkeypatch):
    _clear_tool_environment(monkeypatch)
    monkeypatch.setattr("inksim.integration.paths.shutil.which", lambda name: None)

    status = detect_tools()

    assert not status.has_inkscape
    assert not status.has_inkstitch
    assert not status.can_edit_svg


def test_existing_path_with_spaces_stays_one_argument(monkeypatch, tmp_path):
    executable = tmp_path / "Inkscape App" / "inkscape"
    executable.parent.mkdir()
    executable.write_text("", encoding="utf-8")
    monkeypatch.setenv("INKSCAPE_EXE", str(executable))

    status = detect_tools()

    assert status.inkscape.command == [str(executable)]


def test_inkscape_is_enough_to_attempt_svg_preview():
    status = ToolStatus(
        inkscape=ToolInfo("Inkscape", "/usr/bin/inkscape", "PATH"),
        inkstitch=ToolInfo("Ink/Stitch", None, "missing"),
    )

    assert status.can_edit_svg


def test_build_export_arguments(tmp_path):
    svg_path = tmp_path / "design.svg"
    csv_path = tmp_path / "design.csv"

    arguments = build_inkscape_export_arguments(
        ["/usr/bin/inkscape"],
        svg_path,
        csv_path,
    )

    assert arguments == [
        "/usr/bin/inkscape",
        "--batch-process",
        "--export-type=csv",
        f"--export-filename={csv_path}",
        str(svg_path),
    ]


def test_command_path_is_preserved_for_relative_files(tmp_path, monkeypatch):
    executable = Path("inkscape")
    monkeypatch.setenv("INKSCAPE_EXE", str(executable))
    monkeypatch.chdir(tmp_path)
    (tmp_path / "inkscape").write_text("", encoding="utf-8")

    status = detect_tools()

    assert status.inkscape.command == [str(executable)]


def test_clean_child_environment_removes_virtualenv(tmp_path, monkeypatch):
    venv = tmp_path / "venv"
    venv_bin = venv / "bin"
    venv_bin.mkdir(parents=True)
    system_bin = tmp_path / "system-bin"
    system_bin.mkdir()
    monkeypatch.setenv("VIRTUAL_ENV", str(venv))
    monkeypatch.setenv("PYTHONPATH", str(tmp_path / "src"))
    monkeypatch.setenv("PYTHONHOME", str(venv))
    monkeypatch.setenv("PATH", f"{venv_bin}{os.pathsep}{system_bin}")

    environment = clean_child_environment()

    assert "VIRTUAL_ENV" not in environment
    assert "PYTHONPATH" not in environment
    assert "PYTHONHOME" not in environment
    assert environment["PATH"] == str(system_bin)
