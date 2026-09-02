# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import subprocess
import sys

def test_package_defines_standard_console_and_gui_commands():
    from pathlib import Path
    import tomllib

    project = tomllib.loads(
        (Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]

    assert project["scripts"]["inksim"] == "inksim.cli:main"
    assert project["gui-scripts"]["inksim-gui"] == "inksim.cli:main"


def test_cli_exports_sample_with_simple_and_default_renderers(
    sample_design, tmp_path
):
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    for option, name in (
        ("--simple-png", "simple.png"),
        ("--png", "default.png"),
    ):
        output = tmp_path / name
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "inksim",
                str(sample_design),
                option,
                str(output),
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
