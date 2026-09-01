# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import subprocess
import sys

import pytest


def test_cli_attaches_console_before_help_exits(monkeypatch):
    from inksim import cli

    calls = []
    monkeypatch.setattr(cli, "_attach_windows_console", lambda: calls.append("attach"))
    monkeypatch.setattr(sys, "argv", ["inksim", "--cli", "-h"])

    with pytest.raises(SystemExit) as exit_info:
        cli.main()

    assert exit_info.value.code == 0
    assert calls == ["attach"]


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
