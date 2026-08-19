# InkSim - interactive embroidery simulator and preview renderer.
# Author: Tony Karnigen (initial version)
# Copyright (c) 2026 Tony Karnigen
# SPDX-License-Identifier: GPL-3.0-or-later

import argparse
import os
import signal
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .constants import APP_TITLE
from .debug import configure_logging
from .gui.frame import MainWindow
from .gui.splash import RendererWarmupThread, SplashScreen
from .interconnect import InterconnectServer, send_command
from .runtime import runtime_info_lines


def _parse_pair(value, name, separator):
    """Parse two integer values used for window geometry."""
    parts = value.split(separator)
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(
            f"{name} must use the format VALUE{separator}VALUE"
        )
    try:
        first, second = (int(part) for part in parts)
    except ValueError as ex:
        raise argparse.ArgumentTypeError(f"{name} values must be integers") from ex
    if name == "size" and (first <= 0 or second <= 0):
        raise argparse.ArgumentTypeError("size values must be greater than zero")
    return first, second


def _default_log_path(input_paths):
    project_root = Path.cwd()
    if (project_root / "pyproject.toml").is_file() and (
        project_root / "src" / "inksim"
    ).is_dir():
        return project_root / "log" / "inksim.log"
    if not input_paths:
        return Path("inksim.log")
    input_path = input_paths[0]
    if input_path.is_file():
        return input_path.with_suffix(".log")
    if input_path.is_dir():
        return input_path / "inksim.log"
    return Path("inksim.log")


def main():
    parser = argparse.ArgumentParser(description=APP_TITLE)
    parser.add_argument(
        "-v", "--version", action="store_true",
        help="Show InkSim and runtime dependency information and exit",
    )
    parser.add_argument(
        "input_file",
        nargs="*",
        help="Input embroidery file(s) or directory",
    )
    parser.add_argument(
        "-f", "--fullscreen", action="store_true",
        help="Open the simulator fullscreen",
    )
    parser.add_argument(
        "-p", "--play", action="store_true",
        help="Start simulation playback immediately",
    )
    parser.add_argument(
        "-s", "--server", action="store_true",
        help="Keep the GUI available for local interconnect commands",
    )
    parser.add_argument(
        "--debug", "--dbg", action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--log", type=Path, metavar="FILE",
        help="Write debug logging to FILE (implies --debug)",
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
        help="Export a clean print PNG and exit (default: INPUT-simple.png)",
    )
    parser.add_argument(
        "--png",
        dest="export_shaded_png",
        nargs="?",
        const="",
        metavar="PATH",
        help="Export a shaded print PNG and exit (default: INPUT.png)",
    )
    parser.add_argument(
        "--icon",
        dest="export_icon",
        nargs="?",
        const="",
        metavar="PATH",
        help="Export a 256px preview PNG and exit (default: INPUT_thumb.png)",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=300,
        help="DPI for --simple-png or --png (default: 300)",
    )
    parser.add_argument(
        "--bg",
        dest="export_background",
        choices=("transparent", "white"),
        default="transparent",
        help="PNG background (default: transparent)",
    )
    parser.add_argument(
        "--grid",
        dest="export_grid",
        action="store_true",
        help="Add a measurement grid to exported PNG",
    )
    parser.add_argument(
        "-y", "--yes",
        action="store_true",
        help="Overwrite existing batch export files without asking",
    )
    args = parser.parse_args()
    if args.version:
        print("\n".join(runtime_info_lines()))
        return

    export_values = [
        value for value in (
            args.export_png,
            args.export_shaded_png,
            args.export_icon,
        )
        if value is not None
    ]
    if len(export_values) > 1:
        parser.error("choose only one export option at a time")
    if args.dpi <= 0:
        parser.error("DPI must be greater than zero")
    export_requested = bool(export_values)
    if export_requested and not args.input_file:
        parser.error(
            "an input embroidery file is required for export; "
            "use: inksim INPUT_FILE --simple-png OUTPUT.png"
        )
    input_paths = [Path(value) for value in args.input_file]
    for input_path in input_paths:
        if not (input_path.is_file() or input_path.is_dir()):
            parser.error(f"input path not found: {input_path}")
    if export_requested:
        directories = [path for path in input_paths if path.is_dir()]
        if directories or any(not path.is_file() for path in input_paths):
            parser.error("batch export requires embroidery files, not directories")

    export_paths = []
    if export_requested:
        export_value = export_values[0]
        if args.export_png is not None:
            default_suffix = "-simple.png"
        elif args.export_shaded_png is not None:
            default_suffix = ".png"
        else:
            default_suffix = "_thumb.png"
        explicit_path = Path(export_value) if export_value else None
        if len(input_paths) > 1 and explicit_path is not None:
            if not explicit_path.is_dir():
                parser.error(
                    "an explicit output path for multiple inputs must be "
                    "an existing directory"
                )
            export_paths = [
                explicit_path / f"{input_path.stem}{default_suffix}"
                for input_path in input_paths
            ]
        else:
            export_paths = [
                (input_path.parent / f"{input_path.stem}{default_suffix}")
                if explicit_path is None
                else explicit_path
                for input_path in input_paths
            ]
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

    debug_enabled = args.debug or args.log is not None or bool(
        os.environ.get("INKSIM_DEBUG") or os.environ.get("INKSIM_LOG")
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

    window_size = args.size
    window_position = args.position
    app = QApplication.instance() or QApplication([])
    app.setApplicationName(APP_TITLE)
    app.setApplicationDisplayName(APP_TITLE)
    app.setOrganizationName(APP_TITLE)
    app.setWindowIcon(QIcon(str(
        Path(__file__).parent / "assets" / "app_icons" / "inksim.svg")))
    first_input = input_paths[0] if input_paths else None
    frame = MainWindow(
        fullscreen=args.fullscreen,
        window_size=window_size,
        window_position=window_position,
        server_mode=args.server,
    )
    interconnect = None
    if args.server:
        try:
            interconnect = InterconnectServer(frame)
            if not interconnect.start():
                print(
                    "InkSim server is already running; forwarding command "
                    "to the existing server.",
                    file=sys.stderr,
                )
                command = (
                    {"command": "open", "path": str(first_input), "focus": True}
                    if first_input is not None and first_input.is_file()
                    else {"command": "show", "focus": True}
                )
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
            zip(input_paths, export_paths), 1
        ):
            if not frame.open_file(str(input_path), precompute_density=False):
                success = False
                print(
                    f"[{index}/{total_inputs}] Failed to load {input_path}",
                    file=sys.stderr,
                )
                continue
            exported = frame.export_png(
                export_path,
                icon=args.export_icon is not None,
                dpi=96 if args.export_icon is not None else args.dpi,
                background=args.export_background,
                grid=args.export_grid,
                renderer_key=(
                    "simple" if args.export_png is not None
                    else frame.viewer.active_renderer
                ),
            )
            if exported:
                print(
                    f"[{index}/{total_inputs}] Exported "
                    f"{input_path} -> {export_path}"
                )
            else:
                success = False
                print(
                    f"[{index}/{total_inputs}] Failed to export {input_path}",
                    file=sys.stderr,
                )
        frame.close()
        raise SystemExit(0 if success else 1)
    splash = SplashScreen()
    splash.show_centered()
    splash.set_message("Preparing InkSim...")
    warmup = RendererWarmupThread(app)

    def finish_startup():
        frame.show_initial_window(
            False,
            str(first_input) if first_input and first_input.is_dir() else None,
        )
        if first_input is not None and first_input.is_file():
            splash.set_message(f"Loading {first_input.name}...")
            if not frame.open_file(str(first_input)):
                frame.close()
                splash.close_after()
                app.exit(1)
                return
            if args.play:
                frame.viewer.toggle_auto_play(forward=True)
        splash.set_message("Ready")
        splash.close_after()

    warmup.finished.connect(finish_startup)
    warmup.start()

    def handle_sigint(signum, frame_info):
        app.quit()

    signal.signal(signal.SIGINT, handle_sigint)
    raise SystemExit(app.exec())


if __name__ == "__main__":
    main()
