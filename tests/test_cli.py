# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import subprocess
import sys


def test_package_defines_standard_console_and_gui_commands():
    import tomllib
    from pathlib import Path

    project = tomllib.loads(
        (Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]

    assert project["scripts"]["inksim"] == "inksim.cli:main"
    assert project["gui-scripts"]["inksim-gui"] == "inksim.cli:main"


def test_cli_exports_sample_with_simple_and_default_renderers(sample_design, tmp_path):
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    for option, name in (
        ("--simple-png=", "simple.png"),
        ("--png=", "default.png"),
        ("--webp=", "default.webp"),
    ):
        output = tmp_path / name
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "inksim",
                str(sample_design),
                f"{option}{output}",
                "-y",
            ],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert output.is_file()
        assert output.stat().st_size > 0


def test_cli_exports_with_active_renderer(sample_design, tmp_path):
    """--active-renderer exports using the viewer's currently selected renderer."""
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    output = tmp_path / "active.png"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "inksim",
            str(sample_design),
            f"--png={output}",
            "--active-renderer",
            "-y",
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert output.is_file()
    assert output.stat().st_size > 0


def test_cli_batch_export_from_subdirectory_files(sample_design, tmp_path):
    """Batch export must work when input files live in nested directories."""
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"

    sub_a = tmp_path / "a"
    sub_b = tmp_path / "b" / "nested"
    sub_a.mkdir()
    sub_b.mkdir(parents=True)

    file_a = sub_a / f"one{sample_design.suffix}"
    file_b = sub_b / f"two{sample_design.suffix}"
    file_a.write_bytes(sample_design.read_bytes())
    file_b.write_bytes(sample_design.read_bytes())

    output_dir = tmp_path / "out"
    output_dir.mkdir()

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "inksim",
            str(file_a),
            str(file_b),
            "--icon",
            str(output_dir),
            "-y",
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    ext = sample_design.suffix.lstrip(".").lower()
    expected_a = output_dir / f"one_{ext}_thumb.png"
    expected_b = output_dir / f"two_{ext}_thumb.png"
    assert expected_a.is_file()
    assert expected_a.stat().st_size > 0
    assert expected_b.is_file()
    assert expected_b.stat().st_size > 0
