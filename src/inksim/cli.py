# InkSim - interactive embroidery simulator and preview renderer.
# Author: Tony Karnigen (initial version)
# Copyright (c) 2026 Tony Karnigen
# SPDX-License-Identifier: GPL-3.0-or-later

import argparse
import sys
from pathlib import Path

from PySide6.QtCore import QEventLoop
from PySide6.QtWidgets import QApplication

from .constants import APP_TITLE
from .gui.frame import MainWindow
from .gui.splash import RendererWarmupThread, SplashScreen


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


def main():
    parser = argparse.ArgumentParser(description=APP_TITLE)
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
        help="Add a 10 mm grid to exported PNG",
    )
    parser.add_argument(
        "-y", "--yes",
        action="store_true",
        help="Overwrite existing batch export files without asking",
    )
    args = parser.parse_args()

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

    window_size = args.size
    window_position = args.position
    app = QApplication.instance() or QApplication([])
    first_input = input_paths[0] if input_paths else None
    frame = MainWindow(
        fullscreen=args.fullscreen,
        window_size=window_size,
        window_position=window_position,
    )
    if export_requested:
        success = True
        total_inputs = len(input_paths)
        for index, (input_path, export_path) in enumerate(
            zip(input_paths, export_paths), 1
        ):
            if not frame.open_file(str(input_path)):
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
                shaded=args.export_shaded_png is not None,
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
    warmup = RendererWarmupThread()
    warmup_loop = QEventLoop()
    warmup.finished.connect(warmup_loop.quit)
    warmup.start()
    warmup_loop.exec()
    warmup.wait()
    frame.show_initial_window(
        False,
        str(first_input) if first_input and first_input.is_dir() else None,
    )
    app.processEvents()
    if first_input is not None and first_input.is_file():
        splash.set_message(f"Loading {first_input.name}...")
        if not frame.open_file(str(first_input)):
            frame.close()
            splash.close_after()
            raise SystemExit(1)
        if args.play:
            frame.viewer.ToggleAutoPlay(forward=True)
    splash.set_message("Ready")
    splash.close_after()
    app.exec()


if __name__ == "__main__":
    main()
