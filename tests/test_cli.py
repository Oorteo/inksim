# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import shlex
import subprocess
import sys


def test_server_window_only_shows_splash_before_first_renderer_warmup(qapp, monkeypatch):
    from inksim import cli

    splashes = []
    windows = []

    class FakeSplash:
        def __init__(self):
            splashes.append(self)

        def show_centered(self):
            pass

        def set_message(self, _message):
            pass

        def close_after(self):
            pass

    class FakeWindow:
        def __init__(self, **_options):
            windows.append(self)

        def show_initial_window(self, _autoplay, _initial_directory):
            pass

    def warm_up(_app):
        cli._renderers_warmed = True

    monkeypatch.setattr(cli, "_renderers_warmed", False)
    monkeypatch.setattr(cli, "SplashScreen", FakeSplash)
    monkeypatch.setattr(cli, "MainWindow", FakeWindow)
    monkeypatch.setattr(cli, "_warm_up_renderers", warm_up)

    cli._create_server_window({})
    cli._create_server_window({})

    assert len(splashes) == 1
    assert len(windows) == 2


def test_package_defines_standard_console_and_gui_commands():
    import tomllib
    from pathlib import Path

    project = tomllib.loads(
        (Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]

    assert project["scripts"]["inksim"] == "inksim.cli:main"
    assert project["gui-scripts"]["inksim-gui"] == "inksim.cli:main"


def test_hidden_temporary_input_option_is_forwarded_to_server(monkeypatch, tmp_path):
    import pytest

    from inksim import cli

    parser = cli.build_argument_parser()
    input_path = tmp_path / "preview.csv"
    args = parser.parse_args(["--temporary-input", str(input_path)])
    requests = []
    monkeypatch.setattr(cli, "_ensure_core_application", lambda: None)
    monkeypatch.setattr(
        cli,
        "forward_request",
        lambda request: requests.append(request) or {"ok": True},
    )

    with pytest.raises(SystemExit) as exit_info:
        cli._forward_to_server(parser, args, [input_path])

    assert exit_info.value.code == 0
    assert requests[0]["temporary_input"] is True
    assert "--temporary-input" not in parser.format_help()


def test_manual_launch_passes_current_inksim_launcher_for_extension_check(monkeypatch, tmp_path):
    import pytest

    from inksim import cli

    parser = cli.build_argument_parser()
    launcher = tmp_path / "inksim"
    launcher.touch()
    requests = []
    monkeypatch.setattr(cli, "_ensure_core_application", lambda: None)
    monkeypatch.setattr(cli, "resolve_inksim_launcher", lambda: launcher)
    monkeypatch.setattr(
        cli,
        "forward_request",
        lambda request: requests.append(request) or {"ok": True},
    )

    with pytest.raises(SystemExit) as exit_info:
        cli._forward_to_server(parser, parser.parse_args([]), [], check_inkscape_extension=True)

    assert exit_info.value.code == 0
    assert requests[0]["inksim_launcher"] == str(launcher)


def test_inkscape_extension_invocation_opens_inksim_despite_extension_arguments(monkeypatch):
    import pytest

    from inksim import cli

    requests = []
    monkeypatch.setenv("DOCUMENT_PATH", "/home/user/design.svg")
    monkeypatch.setattr(cli.sys, "argv", ["inksim", "--extension=about", "--id=selection"])
    monkeypatch.setattr(cli, "_ensure_core_application", lambda: None)
    monkeypatch.setattr(
        cli,
        "forward_request",
        lambda request: requests.append(request) or {"ok": True},
    )

    with pytest.raises(SystemExit) as exit_info:
        cli.main()

    assert exit_info.value.code == 0
    assert requests[0]["type"] == "open"
    assert requests[0]["path"] is None
    assert requests[0]["command_line"] == [
        "inksim",
        "--extension=about",
        "--id=selection",
    ]
    assert "inksim_launcher" not in requests[0]


def test_inkstitch_preview_arguments_preserve_ids_and_set_csv_options():
    from inksim.cli import _inkstitch_preview_arguments

    assert _inkstitch_preview_arguments(["--extension", "preview", "--id", "selection"]) == [
        "--extension=output",
        "--format=csv",
        "--skip_palette=true",
        "--id",
        "selection",
    ]
    assert _inkstitch_preview_arguments(
        [
            "--id=selection",
            "--extension=preview",
            "--format=svg",
            "--skip_palette=false",
            "/tmp/current document.svg",
        ]
    ) == [
        "--id=selection",
        "--extension=output",
        "--format=csv",
        "--skip_palette=true",
        "/tmp/current document.svg",
    ]


def test_extract_create_bash_script_flag():
    from inksim.cli import _extract_create_bash_script

    assert _extract_create_bash_script(["--extension=preview"]) == (
        False,
        ["--extension=preview"],
    )
    assert _extract_create_bash_script(
        ["--extension=preview", "--create_bash_script=true", "--id=selection"]
    ) == (True, ["--extension=preview", "--id=selection"])
    assert _extract_create_bash_script(["--extension=preview", "--create_bash_script=false"]) == (
        False,
        ["--extension=preview"],
    )


def test_inkscape_preview_waits_for_csv_then_forwards_temporary_input(
    monkeypatch, tmp_path, capsys
):
    from pathlib import Path
    from types import SimpleNamespace

    import pytest

    from inksim import cli

    extension_dir = tmp_path / "extensions" / "inkstitch"
    extension_dir.mkdir(parents=True)
    script = extension_dir / "inkstitch.py"
    script.write_text("# Ink/Stitch test script\n", encoding="utf-8")
    python = tmp_path / "python"
    python.touch()
    svg_path = tmp_path / "ink_ext_XXXXXX.svg50RMY3"
    svg_path.write_text("<svg />", encoding="utf-8")
    document_dir = tmp_path / "original document"
    document_dir.mkdir()
    document_path = document_dir / "design.svg"
    document_path.write_text("<svg id='original' />", encoding="utf-8")
    status = {
        "status": "found",
        "active_inkstitch": str(extension_dir),
        "inkstitch": [
            {
                "extension_dir": str(extension_dir),
                "command": str(script),
                "location": "inx",
                "interpreter": "python",
            }
        ],
        "python-interpretor": str(python),
    }

    class FakeConfig:
        def get(self, key):
            assert key == cli.INKSCAPE_CONFIG_KEY
            return status

    process_calls = []
    requests = []

    def run(command, **kwargs):
        process_calls.append((command, kwargs))
        assert svg_path.is_file()
        kwargs["stdout"].write(b"csv stitch data")
        return SimpleNamespace(returncode=0, stderr="")

    def forward(request):
        requests.append(request)
        csv_path = Path(request["path"])
        assert csv_path.read_bytes() == b"csv stitch data"
        assert request["temporary_input"] is True
        assert request["autoplay"] is True
        return {"ok": True}

    monkeypatch.setattr(cli, "Config", FakeConfig)
    monkeypatch.setenv("DOCUMENT_PATH", str(document_path))
    monkeypatch.setenv("INKEX_GETTEXT_DIRECTORY", "/inkscape extensions/locale")
    monkeypatch.setattr(cli.subprocess, "run", run)
    monkeypatch.setattr(cli, "_ensure_core_application", lambda: None)
    monkeypatch.setattr(cli, "forward_request", forward)
    monkeypatch.setattr(
        cli.sys,
        "argv",
        [
            "inksim",
            "--extension=preview",
            "--create_bash_script=true",
            "--id=selection",
            str(svg_path),
        ],
    )

    with pytest.raises(SystemExit) as exit_info:
        cli.main()

    assert exit_info.value.code == 0
    assert process_calls[0][0] == [
        str(python),
        str(script),
        "--extension=output",
        "--format=csv",
        "--skip_palette=true",
        "--id=selection",
        str(svg_path),
    ]
    assert process_calls[0][1]["cwd"] == extension_dir
    assert process_calls[0][1]["env"]["INKSTITCH_OFFLINE_SCRIPT"] == "True"
    assert process_calls[0][1]["stdin"] == cli.subprocess.DEVNULL
    assert "--create_bash_script=true" not in process_calls[0][0]
    debug_svg = document_dir / "debug_inksim.svg"
    debug_script = document_dir / "debug_inksim.sh"
    assert debug_svg.read_text(encoding="utf-8") == "<svg />"
    script_contents = debug_script.read_text(encoding="utf-8")
    assert f"cd -- {shlex.quote(str(Path.cwd()))}" in script_contents
    assert f"export DOCUMENT_PATH={shlex.quote(str(document_path))}" in script_contents
    assert f"export INKEX_GETTEXT_DIRECTORY={shlex.quote('/inkscape extensions/locale')}" in (
        script_contents
    )
    assert (
        shlex.join(
            [
                "inksim",
                "--extension=preview",
                "--create_bash_script=true",
                "--id=selection",
                str(debug_svg),
            ]
        )
        in script_contents
    )
    assert "export INKSIM_OFFLINE_SCRIPT=true" in script_contents
    assert "--extension=output" not in script_contents
    assert "INKSTITCH_OFFLINE_SCRIPT" not in script_contents
    assert str(debug_script) in capsys.readouterr().err
    assert (
        cli._create_inksim_debug_script(
            ["--extension=preview", "--create_bash_script=true", str(debug_svg)]
        )
        is None
    )
    assert capsys.readouterr().err == ""
    original_script = debug_script.read_text(encoding="utf-8")
    monkeypatch.setenv("INKSIM_OFFLINE_SCRIPT", "true")
    assert (
        cli._create_inksim_debug_script(
            ["--extension=preview", "--create_bash_script=true", str(svg_path)]
        )
        is None
    )
    assert debug_script.read_text(encoding="utf-8") == original_script
    assert capsys.readouterr().err == ""
    assert requests[0]["command_line"] == [
        "inksim",
        "--extension=preview",
        "--create_bash_script=true",
        "--id=selection",
        str(svg_path),
    ]
    assert requests[0]["debug_script"] == str(debug_script)
    csv_path = Path(requests[0]["path"])
    assert csv_path.is_file()
    csv_path.unlink()


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


def test_cli_rejects_active_renderer_with_simple_png(sample_design, tmp_path):
    """--active-renderer is only meaningful with --png/--webp."""
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    output = tmp_path / "active.png"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "inksim",
            str(sample_design),
            f"--simple-png={output}",
            "--active-renderer",
            "-y",
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "--active-renderer" in result.stderr


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


def test_console_hiding_options_only_apply_on_windows(monkeypatch):
    from inksim import cli

    assert cli._console_hiding_options(platform="posix") == {}
    monkeypatch.setattr(cli.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    assert cli._console_hiding_options(platform="nt") == {"creationflags": 0x08000000}
