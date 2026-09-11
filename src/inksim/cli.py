# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

"""InkSim command-line entry point."""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
from pathlib import Path
from typing import Any

from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .constants import APP_ORGANIZATION, APP_TITLE
from .debug import configure_logging, logger
from .gui.frame import MainWindow
from .gui.splash import RendererWarmupThread, SplashScreen
from .i18n import active_locale, available_locales, set_active_locale
from .interconnect import InterconnectServer, send_command
from .runtime import runtime_info_lines


def _parse_pair(value: str, name: str, separator: str) -> tuple[int, int]:
    """Parse two integer values used for window geometry."""
    parts = value.split(separator)
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(f"{name} must use the format VALUE{separator}VALUE")
    try:
        first, second = (int(part) for part in parts)
    except ValueError as ex:
        raise argparse.ArgumentTypeError(f"{name} values must be integers") from ex
    if name == "size" and (first <= 0 or second <= 0):
        raise argparse.ArgumentTypeError("size values must be greater than zero")
    return first, second


def _write_response_file(output_path: Path, response: dict[str, Any]) -> None:
    """Write a JSON response to ``output_path`` for a GUI-subsystem caller."""
    try:
        output_path.write_text(json.dumps(response), encoding="utf-8")
    except OSError as ex:
        raise SystemExit(f"cannot write response to {output_path}: {ex}")


def _send_command_and_exit(json_text: str, output_path: Path | None = None) -> None:
    """Send a JSON command to a running server and print the response.

    When ``output_path`` is given the JSON response is written to that file
    instead of stdout.  This lets a GUI-subsystem launcher (``inksim-gui`` on
    Windows) report its result without needing an attached console.
    """
    try:
        command = json.loads(json_text)
    except json.JSONDecodeError as ex:
        raise SystemExit(f"invalid JSON command: {ex}")
    logger.debug("IPC probe creating QCoreApplication")
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
        app.setApplicationName(APP_TITLE)
        app.setOrganizationName(APP_ORGANIZATION)
    logger.debug("IPC probe QCoreApplication ready")
    try:
        response = send_command(command)
    except RuntimeError as ex:
        if output_path is not None:
            _write_response_file(output_path, {"ok": False, "error": str(ex)})
        else:
            print(str(ex), file=sys.stderr)
        raise SystemExit(1)
    if output_path is not None:
        _write_response_file(output_path, response)
    else:
        print(json.dumps(response))
    raise SystemExit(0 if response.get("ok") else 1)


def _default_log_path(input_paths: list[Path]) -> Path:
    """Return a sensible default log path based on the working directory."""
    project_root = Path.cwd()
    if (project_root / "pyproject.toml").is_file() and (project_root / "src" / "inksim").is_dir():
        return project_root / "log" / "inksim.log"
    if not input_paths:
        return Path("inksim.log")
    input_path = input_paths[0]
    if input_path.is_file():
        return input_path.with_suffix(".log")
    if input_path.is_dir():
        return input_path / "inksim.log"
    return Path("inksim.log")


def build_argument_parser() -> argparse.ArgumentParser:
    """Return the ArgumentParser used by the inksim command line."""
    parser = argparse.ArgumentParser(description=APP_TITLE)
    parser.add_argument(
        "-v",
        "--version",
        action="store_true",
        help="Show InkSim and runtime dependency information and exit",
    )
    parser.add_argument(
        "-l",
        "--lang",
        "--language",
        choices=available_locales(),
        default=None,
        help="Override the UI language (default: from config or en)",
    )
    parser.add_argument(
        "input_file",
        nargs="*",
        help="Input embroidery file(s) or directory",
    )
    parser.add_argument(
        "-f",
        "--fullscreen",
        action="store_true",
        help="Open the simulator fullscreen",
    )
    parser.add_argument(
        "-p",
        "--play",
        action="store_true",
        help="Start simulation playback immediately",
    )
    parser.add_argument(
        "-s",
        "--server",
        action="store_true",
        help="Keep the GUI available for local interconnect commands",
    )
    parser.add_argument(
        "--delete-input",
        action="store_true",
        help="Delete the first input file after it has been loaded (server mode)",
    )
    parser.add_argument(
        "--document-path",
        type=Path,
        metavar="FILE",
        help="Original document path used as the default directory for open/save dialogs",
    )
    parser.add_argument(
        "--send-command",
        metavar="JSON",
        help="Send one JSON command to a running InkSim server and exit",
    )
    parser.add_argument(
        "--output",
        type=Path,
        metavar="FILE",
        help="Write the --send-command JSON response to FILE instead of stdout",
    )
    parser.add_argument(
        "--debug",
        "--dbg",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--log",
        type=Path,
        metavar="FILE",
        help="Write debug logging to FILE (implies --debug)",
    )
    parser.add_argument(
        "--snap",
        metavar="NAME",
        help="Window-layout profile name to save/restore (e.g. inkstitch)",
    )
    parser.add_argument(
        "--size",
        metavar="WIDTHxHEIGHT",
        type=lambda value: _parse_pair(value, "size", "x"),
        help="Window size, for example 1600x1000",
    )
    parser.add_argument(
        "--position",
        metavar="X,Y",
        type=lambda value: _parse_pair(value, "position", ","),
        help="Window position, for example 100,50",
    )
    parser.add_argument(
        "--simple-png",
        dest="export_png",
        nargs="?",
        const="",
        metavar="PATH",
        help="Export a clean print PNG and exit (default: INPUT_TYPE-simple.png; use --simple-png=PATH)",
    )
    parser.add_argument(
        "--png",
        dest="export_shaded_png",
        nargs="?",
        const="",
        metavar="PATH",
        help="Export a shaded print PNG and exit (default: INPUT_TYPE.png; use --png=PATH)",
    )
    parser.add_argument(
        "--webp",
        dest="export_webp",
        nargs="?",
        const="",
        metavar="PATH",
        help="Export a shaded print WebP and exit (default: INPUT_TYPE.webp; use --webp=PATH)",
    )
    parser.add_argument(
        "--icon",
        dest="export_icon",
        nargs="?",
        const="",
        metavar="PATH",
        help="Export a 256px preview PNG and exit (default: INPUT_TYPE_thumb.png; use --icon=PATH)",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=300,
        help="DPI for --simple-png, --png or --webp (default: 300)",
    )
    parser.add_argument(
        "--bg",
        dest="export_background",
        choices=("transparent", "white"),
        default="transparent",
        help="Background for PNG/WebP export (default: transparent)",
    )
    parser.add_argument(
        "--grid",
        dest="export_grid",
        action="store_true",
        help="Add a measurement grid to exported PNG/WebP",
    )
    parser.add_argument(
        "--active-renderer",
        dest="export_active_renderer",
        action="store_true",
        help="For --png/--webp use the viewer's active renderer instead of the default shaded_volume",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Overwrite existing batch export files without asking",
    )
    return parser


def main() -> None:
    """Run the InkSim command line application."""
    parser = build_argument_parser()
    args = parser.parse_args()
    if args.version:
        print("\n".join(runtime_info_lines()))
        return
    if args.output is not None and not args.send_command:
        parser.error("--output is only meaningful with --send-command")
    if args.send_command:
        debug_enabled = (
            args.debug
            or args.log is not None
            or bool(os.environ.get("INKSIM_DEBUG") or os.environ.get("INKSIM_LOG"))
        )
        log_path = (
            args.log
            or (Path(os.environ["INKSIM_LOG"]) if os.environ.get("INKSIM_LOG") else None)
            or _default_log_path([])
        )
        if debug_enabled:
            try:
                configure_logging(True, log_path)
            except OSError as ex:
                parser.error(f"cannot create debug log {log_path}: {ex}")
        _send_command_and_exit(args.send_command, args.output)

    export_values = [
        value
        for value in (
            args.export_png,
            args.export_shaded_png,
            args.export_webp,
            args.export_icon,
        )
        if value is not None
    ]
    if len(export_values) > 1:
        parser.error("choose only one export option at a time")
    if args.dpi <= 0:
        parser.error("DPI must be greater than zero")
    export_requested = bool(export_values)
    if (
        export_requested
        and args.export_active_renderer
        and not (args.export_shaded_png is not None or args.export_webp is not None)
    ):
        parser.error("--active-renderer can only be used with --png or --webp")
    if export_requested and not args.input_file:
        parser.error(
            "an input embroidery file is required for export; use: inksim INPUT_FILE --simple-png=OUTPUT.png"
        )
    if args.delete_input and not args.server:
        parser.error("--delete-input is only meaningful with --server")
    if args.send_command and (args.server or args.input_file or export_requested):
        parser.error("--send-command cannot be combined with server, export or input files")
    input_paths = [Path(value) for value in args.input_file]
    for input_path in input_paths:
        if not (input_path.is_file() or input_path.is_dir()):
            parser.error(f"input path not found: {input_path}")
    if export_requested:
        directories = [path for path in input_paths if path.is_dir()]
        if directories or any(not path.is_file() for path in input_paths):
            parser.error("batch export requires embroidery files, not directories")

    def _default_export_suffix(input_path: Path, kind: str) -> str:
        """Return a collision-resistant default suffix including the input extension."""
        ext = input_path.suffix.lstrip(".").lower()
        if ext:
            ext_part = f"_{ext}"
        else:
            ext_part = ""
        if kind == "simple":
            return f"{ext_part}-simple.png"
        if kind == "shaded":
            return f"{ext_part}.png"
        if kind == "webp":
            return f"{ext_part}.webp"
        return f"{ext_part}_thumb.png"

    def _export_kind_and_format(args: argparse.Namespace) -> tuple[str, str]:
        if args.export_png is not None:
            return "simple", "PNG"
        if args.export_shaded_png is not None:
            return "shaded", "PNG"
        if args.export_webp is not None:
            return "webp", "WebP"
        return "icon", "PNG"

    export_paths: list[Path] = []
    if export_requested:
        export_value = export_values[0]
        kind, export_format = _export_kind_and_format(args)
        explicit_path = Path(export_value) if export_value else None
        if len(input_paths) > 1 and explicit_path is not None:
            if not explicit_path.is_dir():
                parser.error(
                    "an explicit output path for multiple inputs must be an existing directory"
                )
            export_paths = [
                explicit_path / f"{input_path.stem}{_default_export_suffix(input_path, kind)}"
                for input_path in input_paths
            ]
        else:
            export_paths = [
                (input_path.parent / f"{input_path.stem}{_default_export_suffix(input_path, kind)}")
                if explicit_path is None
                else explicit_path
                for input_path in input_paths
            ]
        if export_format == "WebP":
            export_paths = [path.with_suffix(".webp") for path in export_paths]
        else:
            export_paths = [path.with_suffix(".png") for path in export_paths]
        if len(set(export_paths)) != len(export_paths):
            parser.error("input files produce duplicate output paths")
        if not args.yes:
            existing_paths = [path for path in export_paths if path.exists()]
            if existing_paths:
                prompt = "Overwrite existing file(s)? [y/N] "
                try:
                    answer = input(prompt).strip().lower()
                except EOFError:
                    answer = ""
                if answer not in ("y", "yes"):
                    parser.error("export cancelled")

    if args.lang is not None:
        set_active_locale(args.lang)
    else:
        active_locale()  # resolves config or environment locale

    debug_enabled = (
        args.debug
        or args.log is not None
        or bool(os.environ.get("INKSIM_DEBUG") or os.environ.get("INKSIM_LOG"))
    )
    log_path = (
        args.log
        or (Path(os.environ["INKSIM_LOG"]) if os.environ.get("INKSIM_LOG") else None)
        or _default_log_path(input_paths)
    )
    if debug_enabled:
        try:
            configure_logging(True, log_path)
        except OSError as ex:
            parser.error(f"cannot create debug log {log_path}: {ex}")

    window_size: tuple[int, int] | None = args.size
    window_position: tuple[int, int] | None = args.position
    snap_layout_key: str | None = args.snap
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    app.setApplicationName(APP_TITLE)
    app.setOrganizationName(APP_TITLE)
    app.setWindowIcon(QIcon(str(Path(__file__).parent / "assets" / "app_icons" / "inksim.svg")))
    first_input: Path | None = input_paths[0] if input_paths else None
    document_path: Path | None = args.document_path
    frame = MainWindow(
        fullscreen=args.fullscreen,
        window_size=window_size,
        window_position=window_position,
        server_mode=args.server,
        delete_input=args.delete_input,
        document_path=document_path,
        snap_layout_key=snap_layout_key,
    )
    interconnect: InterconnectServer | None = None
    if args.server:
        try:
            interconnect = InterconnectServer(frame)
            if not interconnect.start():
                print(
                    "InkSim server is already running; forwarding command to the existing server.",
                    file=sys.stderr,
                )
                open_command = "open_and_delete" if args.delete_input else "open"
                command = (
                    {"command": open_command, "path": str(first_input), "focus": True}
                    if first_input is not None and first_input.is_file()
                    else {"command": "show", "focus": True}
                )
                if snap_layout_key:
                    command["snap"] = snap_layout_key
                if document_path is not None and command["command"] == open_command:
                    command["document_path"] = str(document_path)
                if args.play and command["command"] == open_command:
                    command["autoplay"] = True
                response = send_command(command)
                frame.close()
                if not response.get("ok"):
                    parser.error(response.get("error", "server command failed"))
                raise SystemExit(0)
        except RuntimeError as ex:
            frame.close()
            parser.error(str(ex))
        frame.interconnect = interconnect
        app.aboutToQuit.connect(interconnect.stop)
    if export_requested:
        success = True
        total_inputs = len(input_paths)
        for index, (input_path, export_path) in enumerate(
            zip(input_paths, export_paths, strict=False), 1
        ):
            if not frame.open_file(str(input_path), precompute_density=False):
                success = False
                print(
                    f"[{index}/{total_inputs}] Failed to load {input_path}",
                    file=sys.stderr,
                )
                continue
            if args.export_png is not None or args.export_icon is not None:
                renderer_key = "simple"
            elif args.export_active_renderer:
                renderer_key = frame.viewer.active_renderer
            else:
                renderer_key = "shaded_volume"
            exported = frame.export_png(
                export_path,
                icon=args.export_icon is not None,
                dpi=96 if args.export_icon is not None else args.dpi,
                background=args.export_background,
                grid=args.export_grid,
                renderer_key=renderer_key,
                format="WebP" if args.export_webp is not None else "PNG",
            )
            if exported:
                print(f"[{index}/{total_inputs}] Exported {input_path} -> {export_path}")
            else:
                success = False
                print(
                    f"[{index}/{total_inputs}] Failed to export {input_path}",
                    file=sys.stderr,
                )
        frame.close()
        raise SystemExit(0 if success else 1)
    splash: SplashScreen = SplashScreen()
    splash.show_centered()
    splash.set_message("Preparing InkSim...")
    warmup: RendererWarmupThread = RendererWarmupThread(app)

    def finish_startup() -> None:
        frame.show_initial_window(
            False,
            str(first_input) if first_input and first_input.is_dir() else None,
        )
        if first_input is not None and first_input.is_file():
            splash.set_message(f"Loading {first_input.name}...")
            if not frame.open_file(
                str(first_input),
                delete_after_load=args.delete_input,
                autoplay=args.play,
            ):
                splash.close_after()
                frame.open_file_dialog()
                return
            if args.play:
                frame.focus_window()
                frame.viewer.toggle_auto_play(forward=True)
        splash.set_message("Ready")
        splash.close_after()

    warmup.finished.connect(finish_startup)
    warmup.start()

    def handle_sigint(signum: int, frame_info: object) -> None:
        app.quit()

    signal.signal(signal.SIGINT, handle_sigint)
    raise SystemExit(app.exec())


if __name__ == "__main__":
    main()
