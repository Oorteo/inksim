# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Argument parsing shared by the CLI and the GUI help dialog."""

from __future__ import annotations

import argparse
from pathlib import Path

from .constants import APP_TITLE
from .i18n import available_locales


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
        help="Run the singleton InkSim server without a window; other inksim calls are forwarded to it",
    )
    parser.add_argument(
        "--new-window",
        action="store_true",
        help="Ask the running server to open a new window for the input instead of reusing one",
    )
    parser.add_argument(
        "--index",
        type=int,
        default=0,
        metavar="N",
        help="Index of the server window that receives the input (default: 0)",
    )
    parser.add_argument(
        "--stop-server",
        action="store_true",
        help="Close all InkSim windows and stop the running server, then exit",
    )
    parser.add_argument(
        "--delete-input",
        action="store_true",
        help="Delete the input file after it has been loaded",
    )
    parser.add_argument(
        "--temporary-input",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--document-path",
        type=Path,
        metavar="FILE",
        help="Original document path used as the default directory for open/save dialogs",
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
        help="Export a 256px preview PNG and exit (default: INPUT_FILE.png; use --icon=PATH)",
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
