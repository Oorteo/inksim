# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

"""InkSim command-line entry point."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .config import Config
from .constants import APP_TITLE
from .debug import configure_logging
from .gui.frame import MainWindow
from .gui.splash import RendererWarmupThread, SplashScreen
from .i18n import active_locale, available_locales, set_runtime_locale
from .integration.inkstitch import inkstitch_process_environment, resolve_inkstitch_preview
from .integration.paths import INKSCAPE_CONFIG_KEY
from .ipc import IpcUnavailable, send_request
from .runtime import runtime_info_lines
from .server import InkSimServer, forward_request, idle_timeout_seconds


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


_renderers_warmed = False


def _warm_up_renderers(app: QApplication) -> None:
    """Compile the Numba renderers once, keeping the splash responsive meanwhile."""
    global _renderers_warmed
    if _renderers_warmed:
        return
    warmup = RendererWarmupThread(app)
    warmup.start()
    while warmup.isRunning():
        app.processEvents()
        warmup.wait(20)
    _renderers_warmed = True


def _create_server_window(options: dict[str, Any]) -> MainWindow:
    """Create and show a viewer window for the server from client-supplied options."""
    app = QApplication.instance()
    splash: SplashScreen | None = None
    if isinstance(app, QApplication):
        splash = SplashScreen()
        splash.show_centered()
        splash.set_message("Preparing InkSim...")
        app.processEvents()
        _warm_up_renderers(app)
    window_size = options.get("window_size")
    window_position = options.get("window_position")
    document_path = options.get("document_path")
    window = MainWindow(
        fullscreen=bool(options.get("fullscreen")),
        window_size=tuple(window_size) if window_size else None,
        window_position=tuple(window_position) if window_position else None,
        document_path=Path(document_path) if document_path else None,
        snap_layout_key=options.get("snap_layout_key"),
    )
    window.show_initial_window(False, None)
    if splash is not None:
        splash.close_after()
    return window


def _configure_application(app: QCoreApplication) -> None:
    app.setApplicationName(APP_TITLE)
    app.setOrganizationName(APP_TITLE)
    if isinstance(app, QApplication):
        app.setWindowIcon(QIcon(str(Path(__file__).parent / "assets" / "app_icons" / "inksim.svg")))


def _run_server(app: QApplication) -> None:
    """Run the singleton server until its idle timeout or an explicit shutdown."""
    app.setQuitOnLastWindowClosed(False)
    server = InkSimServer(app, _create_server_window, idle_timeout_seconds())
    if not server.start():
        print("InkSim server is already running.", file=sys.stderr)
        raise SystemExit(0)
    signal.signal(signal.SIGINT, lambda signum, frame_info: app.quit())
    raise SystemExit(app.exec())


def _ensure_core_application() -> QCoreApplication:
    """Return a non-GUI application so the client can use Qt local sockets."""
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
        app.setApplicationName(APP_TITLE)
        app.setOrganizationName(APP_TITLE)
    return app


def _stop_server() -> None:
    _ensure_core_application()
    try:
        send_request({"type": "shutdown"})
    except IpcUnavailable:
        print("InkSim server is not running.")
        raise SystemExit(0)
    print("InkSim server is shutting down.")
    raise SystemExit(0)


def _is_inkscape_extension_invocation(arguments: list[str]) -> bool:
    return any(
        argument == "--extension" or argument.startswith("--extension=") for argument in arguments
    )


def _extension_name(arguments: list[str]) -> str | None:
    for index, argument in enumerate(arguments):
        if argument == "--extension":
            return arguments[index + 1] if index + 1 < len(arguments) else None
        if argument.startswith("--extension="):
            return argument.partition("=")[2]
    return None


def _inkstitch_preview_arguments(arguments: list[str]) -> list[str]:
    """Translate InkSim's preview extension arguments into Ink/Stitch output arguments."""
    result: list[str] = []
    preview_extension_found = False
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--extension":
            if index + 1 >= len(arguments):
                raise ValueError("The --extension argument requires a value.")
            if arguments[index + 1] != "preview":
                raise ValueError("InkSim preview can only forward --extension=preview.")
            result.append("--extension=output")
            preview_extension_found = True
            index += 2
        elif argument.startswith("--extension="):
            if argument.partition("=")[2] != "preview":
                raise ValueError("InkSim preview can only forward --extension=preview.")
            result.append("--extension=output")
            preview_extension_found = True
            index += 1
        elif argument == "--format" or argument.startswith("--format="):
            index += (
                2
                if argument == "--format"
                and index + 1 < len(arguments)
                and not arguments[index + 1].startswith("--")
                else 1
            )
        elif argument == "--skip_palette" or argument.startswith("--skip_palette="):
            index += (
                2
                if argument == "--skip_palette"
                and index + 1 < len(arguments)
                and not arguments[index + 1].startswith("--")
                else 1
            )
        else:
            result.append(argument)
            index += 1

    if not preview_extension_found:
        raise ValueError("Missing --extension=preview argument.")
    extension_index = result.index("--extension=output")
    result[extension_index + 1 : extension_index + 1] = [
        "--format=csv",
        "--skip_palette=true",
    ]
    return result


def _remove_temporary_csv(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as error:
        print(f"Warning: could not remove temporary Ink/Stitch CSV: {error}", file=sys.stderr)


def _run_inkscape_preview(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    extension_arguments: list[str],
) -> None:
    """Wait for Ink/Stitch to export Inkscape's temporary SVG, then display its CSV."""
    try:
        output_arguments = _inkstitch_preview_arguments(extension_arguments)
    except ValueError as error:
        parser.error(str(error))

    status = Config().get(INKSCAPE_CONFIG_KEY)
    preview = resolve_inkstitch_preview(status) if isinstance(status, dict) else None
    if preview is None:
        parser.error("The active Ink/Stitch extension or its Python interpreter was not found.")
    script_path, python_path, extension_dir = preview
    command = [str(python_path), str(script_path)] if python_path else [str(script_path)]

    try:
        with tempfile.NamedTemporaryFile(
            prefix="inksim-preview-",
            suffix=".csv",
            delete=False,
        ) as temporary_csv:
            csv_path = Path(temporary_csv.name)
    except OSError as error:
        parser.error(f"Could not create a temporary Ink/Stitch CSV: {error}")

    retained = False
    try:
        try:
            with csv_path.open("wb") as csv_file:
                result = subprocess.run(
                    [*command, *output_arguments],
                    cwd=script_path.parent,
                    env=inkstitch_process_environment(extension_dir, status),
                    stdout=csv_file,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=180,
                    check=False,
                )
            has_output = csv_path.is_file() and csv_path.stat().st_size > 0
        except subprocess.TimeoutExpired as error:
            print("Ink/Stitch CSV export timed out.", file=sys.stderr)
            if error.stderr:
                stderr_text = (
                    error.stderr.decode("utf-8", "replace")
                    if isinstance(error.stderr, bytes)
                    else error.stderr
                )
                print(stderr_text.rstrip(), file=sys.stderr)
            raise SystemExit(1) from None
        except OSError as error:
            print(f"Could not run Ink/Stitch CSV export: {error}", file=sys.stderr)
            raise SystemExit(1) from error

        if result.returncode != 0 or not has_output:
            print("Ink/Stitch CSV export failed.", file=sys.stderr)
            if result.stderr:
                print(result.stderr.rstrip(), file=sys.stderr)
            raise SystemExit(1)

        try:
            _forward_to_server(parser, args, [csv_path], temporary_input=True)
        except SystemExit as error:
            retained = error.code == 0
            raise
    finally:
        if not retained:
            _remove_temporary_csv(csv_path)


def _forward_to_server(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    input_paths: list[Path],
    *,
    temporary_input: bool | None = None,
) -> None:
    """Ask the singleton server to show the first input, then exit the client."""
    _ensure_core_application()
    request: dict[str, Any] = {
        "type": "open",
        "index": args.index,
        "new_window": args.new_window,
        "path": str(input_paths[0]) if input_paths else None,
        "autoplay": args.play,
        "delete_after_load": args.delete_input,
        "temporary_input": (args.temporary_input if temporary_input is None else temporary_input),
        "command_line": sys.argv.copy(),
        "document_path": str(args.document_path) if args.document_path else None,
        "window": {
            "fullscreen": args.fullscreen,
            "window_size": args.size,
            "window_position": args.position,
            "snap_layout_key": args.snap,
        },
    }
    try:
        response = forward_request(request)
    except IpcUnavailable as ex:
        parser.error(str(ex))
    if not response.get("ok"):
        print(response.get("error", "InkSim server request failed"), file=sys.stderr)
        raise SystemExit(1)
    raise SystemExit(0)


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
    command_line = sys.argv[1:]
    if _is_inkscape_extension_invocation(command_line):
        args = parser.parse_args([])
        if _extension_name(command_line) == "preview":
            _run_inkscape_preview(parser, args, command_line)
        _forward_to_server(parser, args, [])
        return
    args = parser.parse_args(command_line)
    if args.version:
        print("\n".join(runtime_info_lines()))
        return
    debug_enabled = (
        args.debug
        or args.log is not None
        or bool(os.environ.get("INKSIM_DEBUG") or os.environ.get("INKSIM_LOG"))
    )
    log_path = (
        args.log
        or (Path(os.environ["INKSIM_LOG"]) if os.environ.get("INKSIM_LOG") else None)
        or _default_log_path([Path(value) for value in args.input_file])
    )
    if debug_enabled:
        try:
            configure_logging(True, log_path)
        except OSError as ex:
            parser.error(f"cannot create debug log {log_path}: {ex}")
    if args.index < 0:
        parser.error("--index must be zero or greater")
    if args.stop_server:
        _stop_server()

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
    if export_requested and args.new_window:
        parser.error("--new-window cannot be combined with export options")
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
        set_runtime_locale(args.lang)
    else:
        active_locale()  # resolves config or environment locale

    window_size: tuple[int, int] | None = args.size
    window_position: tuple[int, int] | None = args.position
    snap_layout_key: str | None = args.snap
    document_path: Path | None = args.document_path
    if args.server:
        existing_app = QApplication.instance()
        gui_app = existing_app if isinstance(existing_app, QApplication) else QApplication([])
        _configure_application(gui_app)
        _run_server(gui_app)
    if not export_requested:
        _forward_to_server(parser, args, input_paths)
    existing_app = QApplication.instance()
    gui_app = existing_app if isinstance(existing_app, QApplication) else QApplication([])
    _configure_application(gui_app)
    frame = MainWindow(
        fullscreen=args.fullscreen,
        window_size=window_size,
        window_position=window_position,
        document_path=document_path,
        snap_layout_key=snap_layout_key,
    )
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


if __name__ == "__main__":
    main()
