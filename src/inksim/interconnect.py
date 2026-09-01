# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Local JSON-line interconnect for controlling a running InkSim window."""

import json
import os
import secrets
from pathlib import Path

from PySide6.QtCore import QObject, QStandardPaths, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from .debug import logger
from .constants import (
    APP_ORGANIZATION,
    APP_TITLE,
    IPC_PROTOCOL_VERSION,
    IPC_SERVER_NAME,
    TOKEN_FILENAME,
)


def _token_path():
    """Return the path where the active server's auth token is stored."""
    config_dir = Path(QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.ConfigLocation
    ))
    config_dir = config_dir / APP_ORGANIZATION / APP_TITLE
    config_dir.mkdir(parents=True, exist_ok=True)
    token_path = config_dir / TOKEN_FILENAME
    logger.debug("IPC token path: %s", token_path)
    return token_path


def read_auth_token():
    """Read the auth token of the currently running server, if any."""
    token_file = _token_path()
    try:
        token = token_file.read_text(encoding="utf-8").strip()
    except OSError:
        logger.debug("IPC token is unavailable")
        return None
    logger.debug("IPC token is available")
    return token


def write_auth_token(token):
    """Write the auth token so that clients can authenticate."""
    token_file = _token_path()
    token_file.write_text(token, encoding="utf-8")
    # Restrict read access to the owner on Unix-like systems.
    try:
        os.chmod(token_file, 0o600)
    except OSError:
        pass
    logger.debug("IPC token written to %s", token_file)
    return token_file


def clear_auth_token():
    """Remove the auth token when the server shuts down."""
    try:
        _token_path().unlink()
    except OSError:
        pass


class InterconnectServer(QObject):
    """Accept local commands from external embroidery applications."""

    error = Signal(str)

    def __init__(self, window, server_name=IPC_SERVER_NAME):
        super().__init__(window)
        self.window = window
        self.server_name = server_name
        self.server = QLocalServer(self)
        self.server.newConnection.connect(self._accept_connections)
        self._buffers = {}
        self._auth_token = secrets.token_urlsafe(32)
        self._supported_commands = {
            "hello",
            "open",
            "open_and_delete",
            "play",
            "focus",
            "show",
            "hide",
            "quit",
        }

    @property
    def auth_token(self):
        return self._auth_token

    def start(self):
        """Start listening, returning False when another server is active."""
        logger.debug("IPC server starting: %s", self.server_name)
        if self.server.listen(self.server_name):
            write_auth_token(self._auth_token)
            logger.debug("IPC server listening: %s", self.server_name)
            return True
        logger.debug("IPC server listen failed: %s", self.server.errorString())
        probe = QLocalSocket(self)
        probe.connectToServer(self.server_name)
        active = probe.waitForConnected(150)
        probe.abort()
        probe.deleteLater()
        if active:
            logger.debug("IPC endpoint is owned by another server")
            return False
        logger.debug("IPC endpoint recovery: %s", self.server_name)
        QLocalServer.removeServer(self.server_name)
        if self.server.listen(self.server_name):
            write_auth_token(self._auth_token)
            logger.debug("IPC server listening after recovery: %s", self.server_name)
            return True
        logger.debug("IPC server recovery failed: %s", self.server.errorString())
        self.error.emit(self.server.errorString())
        return False

    def stop(self):
        """Stop listening and remove the local endpoint."""
        self.server.close()
        QLocalServer.removeServer(self.server_name)
        clear_auth_token()

    def _accept_connections(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            logger.debug("IPC server accepted a connection")
            self._buffers[socket] = bytearray()
            socket.readyRead.connect(
                lambda socket=socket: self._read_socket(socket)
            )
            socket.disconnected.connect(
                lambda socket=socket: self._forget_socket(socket)
            )

    def _forget_socket(self, socket):
        self._buffers.pop(socket, None)
        try:
            socket.deleteLater()
        except RuntimeError:
            # Qt may have deleted the socket immediately after disconnect.
            pass

    def _read_socket(self, socket):
        self._buffers[socket].extend(bytes(socket.readAll()))
        while b"\n" in self._buffers[socket]:
            raw, remainder = self._buffers[socket].split(b"\n", 1)
            self._buffers[socket] = bytearray(remainder)
            try:
                request = json.loads(raw.decode("utf-8"))
                logger.debug("IPC server received command: %s", request.get("command"))
                response = self._dispatch(request)
            except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as ex:
                logger.debug("IPC server rejected command: %s", ex)
                response = {"ok": False, "error": str(ex)}
            socket.write((json.dumps(response) + "\n").encode("utf-8"))
            socket.flush()
            logger.debug("IPC server sent response: ok=%s", response.get("ok"))

    def _check_auth(self, request):
        """Validate protocol version and auth token."""
        version = request.get("protocol_version")
        if version is not None and version != IPC_PROTOCOL_VERSION:
            raise ValueError(
                f"unsupported protocol version {version}; "
                f"expected {IPC_PROTOCOL_VERSION}"
            )
        token = request.get("auth_token")
        if token != self._auth_token:
            raise ValueError("invalid or missing auth token")

    def _dispatch(self, request):
        if not isinstance(request, dict):
            raise ValueError("command must be a JSON object")
        command = request.get("command")
        if command == "hello":
            return {
                "ok": True,
                "command": "hello",
                "protocol_version": IPC_PROTOCOL_VERSION,
                "server_version": "1.0.0",
                "commands": sorted(self._supported_commands),
            }
        if command not in self._supported_commands:
            raise ValueError(f"unknown command: {command!r}")
        self._check_auth(request)
        if command in ("open", "open_and_delete"):
            path = request.get("path")
            if not isinstance(path, str) or not path:
                raise ValueError("open requires a non-empty path")
            document_path = request.get("document_path")
            if isinstance(document_path, str) and document_path:
                self.window.set_document_path(Path(document_path))
            delete_after_load = command == "open_and_delete"
            autoplay = request.get("autoplay", False)
            opened = self.window.open_file(
                path,
                delete_after_load=delete_after_load,
                autoplay=autoplay,
            )
            if not opened:
                return {"ok": False, "command": command, "path": path}
            if autoplay:
                self.window.focus_window()
                self.window.viewer.toggle_auto_play(forward=True)
            elif request.get("focus", True):
                self.window.focus_window()
            return {"ok": True, "command": command, "path": path}
        if command == "focus":
            self.window.focus_window()
            return {"ok": True, "command": "focus"}
        if command == "play":
            self.window.play()
            return {"ok": True, "command": "play"}
        if command == "show":
            self.window.show_window(focus=request.get("focus", True))
            return {"ok": True, "command": "show"}
        if command == "hide":
            self.window.hide()
            return {"ok": True, "command": "hide"}
        if command == "quit":
            self.window.request_quit()
            return {"ok": True, "command": "quit"}
        raise ValueError(f"unknown command: {command!r}")


def send_command(command, server_name=IPC_SERVER_NAME, timeout=1000):
    """Send one command to a running InkSim server and return its response."""
    logger.debug("IPC client sending command to %s: %s", server_name, command.get("command"))
    token = read_auth_token()
    if token is None:
        raise RuntimeError("InkSim server has no auth token (not running?)")
    command = dict(command)
    command["auth_token"] = token
    command["protocol_version"] = IPC_PROTOCOL_VERSION
    socket = QLocalSocket()
    socket.connectToServer(server_name)
    if not socket.waitForConnected(timeout):
        logger.debug("IPC client connection failed: %s", socket.errorString())
        raise RuntimeError(f"cannot connect to InkSim server: {socket.errorString()}")
    logger.debug("IPC client connected")
    socket.write((json.dumps(command) + "\n").encode("utf-8"))
    if not socket.waitForBytesWritten(timeout) or not socket.waitForReadyRead(timeout):
        logger.debug("IPC client response wait failed: %s", socket.errorString())
        raise RuntimeError("InkSim server did not respond")
    response = bytes(socket.readLine()).decode("utf-8").strip()
    socket.disconnectFromServer()
    logger.debug("IPC client received response")
    return json.loads(response)