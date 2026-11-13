# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Singleton InkSim server that owns the viewer windows.

The server is the same ``inksim`` program started with ``--server``. It has no
window of its own. It keeps the ordered list of open viewer windows, so index 0
is the default target for ``inksim`` clients and external scripts.
"""

from __future__ import annotations

import functools
import hashlib
import importlib.metadata
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication

from .config import Config
from .constants import IPC_PROTOCOL_VERSION, IPC_SERVER_NAME
from .debug import logger
from .ipc import IpcServer, IpcUnavailable, Request, Response, endpoint_is_active, send_request

if TYPE_CHECKING:
    from .gui.frame import MainWindow

DEFAULT_IDLE_TIMEOUT_SECONDS = 300
SERVER_START_TIMEOUT_SECONDS = 120.0
SERVER_OPEN_TIMEOUT_SECONDS = 120.0
SERVER_STOP_TIMEOUT_SECONDS = 5.0
SERVER_ARGS = ["-m", "inksim", "--server"]


def app_version() -> str:
    """Return the installed InkSim version used for the server handshake."""
    return importlib.metadata.version("inksim")


@functools.cache
def code_fingerprint() -> str:
    """Return a hash of the installed InkSim sources.

    Unlike the version or a git commit, this changes with uncommitted edits too,
    so a server running stale code is replaced even when the version is unchanged.
    """
    if getattr(sys, "frozen", False):
        raise NotImplementedError("Frozen builds are not supported by the InkSim server yet")
    package_dir = Path(__file__).parent
    digest = hashlib.sha256()
    for path in sorted(package_dir.rglob("*.py")):
        digest.update(path.relative_to(package_dir).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def idle_timeout_seconds() -> int:
    """Return the configured idle shutdown delay; 0 keeps the server running."""
    return int(Config().get("server_idle_timeout", DEFAULT_IDLE_TIMEOUT_SECONDS))


def spawn_detached(args: list[str]) -> subprocess.Popen[bytes]:
    """Start ``sys.executable`` with *args* in a process that outlives the caller."""
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    executable = sys.executable
    if sys.platform == "win32":
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        if pythonw.exists():
            executable = str(pythonw)
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.CREATE_NO_WINDOW
        )
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen([executable, *args], **kwargs)


def _hello_or_none() -> Response | None:
    try:
        return send_request({"type": "hello"}, timeout_ms=1000)
    except IpcUnavailable:
        return None


def _wait_until_stopped(timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    while endpoint_is_active() and time.monotonic() < deadline:
        time.sleep(0.05)


def forward_request(request: Request) -> Response:
    """Send *request* to the InkSim server, starting or replacing it when needed.

    A running server with a different app or protocol version is asked to shut
    down, then a fresh server is started from the installed code.
    """
    hello = _hello_or_none()
    if hello is not None and (
        hello.get("app_version") != app_version()
        or hello.get("protocol_version") != IPC_PROTOCOL_VERSION
        or hello.get("code_fingerprint") != code_fingerprint()
    ):
        logger.debug("Replacing InkSim server %s", hello)
        try:
            send_request({"type": "shutdown"})
        except IpcUnavailable:
            pass
        _wait_until_stopped(SERVER_STOP_TIMEOUT_SECONDS)
        hello = None
    if hello is None:
        server_process = spawn_detached(SERVER_ARGS)
        started_at = time.monotonic()
        deadline = started_at + SERVER_START_TIMEOUT_SECONDS
        logger.debug(
            "Started InkSim server process %s; waiting up to %.1f seconds",
            server_process.pid,
            SERVER_START_TIMEOUT_SECONDS,
        )
        while hello is None and time.monotonic() < deadline:
            time.sleep(0.05)
            hello = _hello_or_none()
        if hello is None:
            elapsed = time.monotonic() - started_at
            return_code = server_process.poll()
            process_status = (
                "still running" if return_code is None else f"exited with code {return_code}"
            )
            message = (
                f"InkSim server did not respond within {elapsed:.1f} seconds "
                f"(process {server_process.pid} {process_status})."
            )
            logger.error(message)
            raise IpcUnavailable(message)
        logger.debug("InkSim server responded after %.2f seconds", time.monotonic() - started_at)
    if request.get("type") == "open":
        return send_request(
            request,
            timeout_ms=int(SERVER_OPEN_TIMEOUT_SECONDS * 1000),
        )
    return send_request(request)


class InkSimServer(QObject):
    """Own the ordered list of viewer windows and answer local client requests."""

    def __init__(
        self,
        app: QApplication,
        create_window: Callable[[dict[str, Any]], MainWindow],
        idle_timeout: int,
        server_name: str = IPC_SERVER_NAME,
    ) -> None:
        super().__init__()
        self._app = app
        self._create_window = create_window
        self._idle_timeout = idle_timeout
        self.windows: list[MainWindow] = []
        self._stopping = False
        self._ipc = IpcServer(self._handle_request, server_name, self)
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.timeout.connect(self._on_idle_timeout)

    def start(self) -> bool:
        """Start listening; return False when another server already owns the endpoint."""
        if not self._ipc.start():
            return False
        self._restart_idle_timer()
        return True

    def quit_all(self, relaunch_args: list[str] | None = None) -> None:
        """Close every window and stop the server.

        When *relaunch_args* is given, a client with those arguments is started
        after the endpoint is released, so it creates a fresh server.
        """
        self._stopping = True
        self._idle_timer.stop()
        self._ipc.stop()
        for window in list(self.windows):
            window.set_hide_on_close(False)
            window.close()
        self.windows.clear()
        if relaunch_args is not None:
            spawn_detached(["-m", "inksim", *relaunch_args])
        self._app.quit()

    def _handle_request(self, request: Request) -> Response:
        handlers: dict[str, Callable[[Request], Response]] = {
            "hello": self._hello,
            "status": self._status,
            "open": self._open,
            "shutdown": self._shutdown,
        }
        handler = handlers.get(str(request.get("type")))
        if handler is None:
            return {"ok": False, "error": f"unknown request type: {request.get('type')}"}
        return handler(request)

    def _hello(self, request: Request) -> Response:
        return {
            "ok": True,
            "app_version": app_version(),
            "code_fingerprint": code_fingerprint(),
            "protocol_version": IPC_PROTOCOL_VERSION,
            "windows": len(self.windows),
        }

    def _status(self, request: Request) -> Response:
        return {"ok": True, "windows": len(self.windows)}

    def _shutdown(self, request: Request) -> Response:
        # Reply first; the quit runs after the response has been written.
        QTimer.singleShot(0, self.quit_all)
        return {"ok": True}

    def _open(self, request: Request) -> Response:
        if request.get("protocol_version") != IPC_PROTOCOL_VERSION:
            return {"ok": False, "error": "protocol version mismatch"}
        index = int(request.get("index", 0))
        if request.get("new_window") or not self.windows:
            window = self._create_window(request.get("window") or {})
            self._adopt(window)
        elif 0 <= index < len(self.windows):
            window = self.windows[index]
        else:
            return {"ok": False, "error": f"no InkSim window with index {index}"}
        self._idle_timer.stop()

        command_line = request.get("command_line")
        if isinstance(command_line, list) and all(
            isinstance(argument, str) for argument in command_line
        ):
            window.set_command_line_args(command_line)

        launcher_path = request.get("inksim_launcher")

        def schedule_inkscape_extension_check() -> None:
            if isinstance(launcher_path, str):
                QTimer.singleShot(
                    0,
                    lambda: window.check_inkscape_extension(launcher_path),
                )

        document_path = request.get("document_path")
        if document_path:
            window.set_document_path(Path(document_path))
        path = request.get("path")
        if path is None:
            window.focus_window()
            self._restart_idle_timer()
            schedule_inkscape_extension_check()
            return {"ok": True, "index": self.windows.index(window)}
        if Path(path).is_dir():
            window.last_directory = str(Path(path).resolve())
            window.focus_window()
            self._restart_idle_timer()
            schedule_inkscape_extension_check()
            QTimer.singleShot(0, window.open_browser_dialog)
            return {"ok": True, "index": self.windows.index(window)}
        selected_path = Path(path)
        autoplay = bool(request.get("autoplay"))
        delete_after_load = bool(request.get("delete_after_load"))
        temporary_input = bool(request.get("temporary_input"))
        reuse_loaded_file = not delete_after_load and window.has_unchanged_file(
            selected_path, temporary_input
        )
        is_svg = (
            selected_path.suffix.lower() == ".svg"
            and selected_path.is_file()
            and not temporary_input
        )
        loaded = reuse_loaded_file or window.open_file(
            path,
            delete_after_load=delete_after_load,
            autoplay=autoplay,
            temporary_input=temporary_input,
            show_error_dialog=not is_svg,
        )
        if not loaded and is_svg:
            window.open_browser_dialog(selected_file=selected_path.resolve())
            window.focus_window()
            self._restart_idle_timer()
            schedule_inkscape_extension_check()
            return {"ok": True, "index": self.windows.index(window)}
        if not loaded:
            self._restart_idle_timer()
            return {"ok": False, "error": f"cannot open {path}"}
        if autoplay and (not reuse_loaded_file or not window.viewer.is_playing):
            window.viewer.toggle_auto_play(forward=True)
        window.focus_window()
        self._restart_idle_timer()
        schedule_inkscape_extension_check()
        return {"ok": True, "index": self.windows.index(window)}

    def _adopt(self, window: MainWindow) -> None:
        self.windows.append(window)
        window.set_hide_on_close(True)
        window.closed.connect(self._on_window_closed)
        window.hidden.connect(self._on_window_hidden)
        window.quit_all_requested.connect(self.quit_all)
        window.restart_requested.connect(self.quit_all)
        self._restart_idle_timer()

    def _on_window_closed(self, window: MainWindow) -> None:
        if window in self.windows:
            self.windows.remove(window)
        self._restart_idle_timer()

    def _on_window_hidden(self, window: MainWindow) -> None:
        if window in self.windows:
            self._restart_idle_timer()

    def _restart_idle_timer(self) -> None:
        self._idle_timer.stop()
        if self._stopping:
            return
        if not any(window.isVisible() for window in self.windows) and self._idle_timeout > 0:
            self._idle_timer.start(self._idle_timeout * 1000)

    def _on_idle_timeout(self) -> None:
        if not any(window.isVisible() for window in self.windows):
            self.quit_all()
