# InkSim - interactive embroidery simulator and preview renderer.
# Author: Tony Karnigen (initial version)
# Copyright (c) 2026 Tony Karnigen
# SPDX-License-Identifier: GPL-3.0-or-later

import argparse
from pathlib import Path

import wx

from .constants import APP_TITLE
from .gui.frame import Frame


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
        nargs="?",
        help="Input embroidery file or directory",
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
        metavar="PATH",
        help="Export a clean print PNG and exit",
    )
    parser.add_argument(
        "--png",
        dest="export_shaded_png",
        metavar="PATH",
        help="Export a shaded print PNG and exit",
    )
    parser.add_argument(
        "--icon",
        dest="export_icon",
        metavar="PATH",
        help="Export a clean 256px preview PNG and exit",
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
    args=parser.parse_args()

    export_paths = [
        path for path in (
            args.export_png,
            args.export_shaded_png,
            args.export_icon,
        )
        if path
    ]
    if len(export_paths) > 1:
        parser.error("choose only one export option at a time")
    if args.dpi <= 0:
        parser.error("DPI must be greater than zero")
    export_requested = bool(export_paths)
    if export_requested and not args.input_file:
        parser.error(
            "an input embroidery file is required for export; "
            "use: inksim INPUT_FILE --simple-png OUTPUT.png"
        )
    input_path = Path(args.input_file) if args.input_file else None
    if input_path and not (input_path.is_file() or input_path.is_dir()):
        parser.error(f"input path not found: {args.input_file}")
    if export_requested and input_path and not input_path.is_file():
        parser.error("an input embroidery file is required for export")

    window_size = args.size
    window_position = args.position
    app=wx.App(not export_requested)
    frame = Frame(
        initial_file=str(input_path) if input_path and input_path.is_file() else None,
        initial_directory=(
            str(input_path) if input_path and input_path.is_dir() else None
        ),
        fullscreen=args.fullscreen,
        window_size=window_size,
        window_position=window_position,
        autoplay=args.play,
        batch=export_requested,
    )
    if export_requested:
        export_path = export_paths[0]
        success = frame.ExportPng(
            export_path,
            icon=bool(args.export_icon),
            dpi=96 if args.export_icon else args.dpi,
            background=args.export_background,
            grid=args.export_grid,
            shaded=bool(args.export_shaded_png),
        )
        frame.Destroy()
        raise SystemExit(0 if success else 1)
    app.MainLoop()


if __name__ == "__main__":
    main()
