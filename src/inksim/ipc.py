# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Local request/response transport between the InkSim server and its clients.

Messages are UTF-8 JSON objects terminated by a newline. The transport uses
``QLocalServer``, which maps to a named pipe on Windows and a Unix domain
socket elsewhere. New request types only need a handler branch in
:mod:`inksim.server`; the framing here stays unchanged.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from .constants import IPC_PROTOCOL_VERSION, IPC_SERVER_NAME
from .debug import logger

Request = dict[str, Any]
Response = dict[str, Any]
RequestHandler = Callable[[Request], Response]

DEFAULT_TIMEOUT_MS = 10000


class IpcUnavailable(RuntimeError):
    """Raised when no InkSim server answers on the local endpoint."""


def endpoint_is_active(server_name: str = IPC_SERVER_NAME, timeout_ms: int = 500) -> bool:
    """Return True when a process is already listening on the endpoint."""
    probe = QLocalSocket()
    probe.connectToServer(server_name)
    active = probe.waitForConnected(timeout_ms)
    probe.abort()
    return active


class IpcServer(QObject):
    """Accept local clients and pass each decoded request to ``handler``."""

    def __init__(
        self,
        handler: RequestHandler,
        server_name: str = IPC_SERVER_NAME,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._handler = handler
        self.server_name = server_name
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._accept_connections)
        self._buffers: dict[QLocalSocket, bytearray] = {}

    def start(self) -> bool:
        """Start listening; return False when another server owns the endpoint."""
        if endpoint_is_active(self.server_name):
            logger.debug("IPC endpoint is owned by another server")
            return False
        if self._server.listen(self.server_name):
            return True
        # A stale Unix socket file can survive a crash. Remove it and retry once.
        QLocalServer.removeServer(self.server_name)
        if self._server.listen(self.server_name):
            return True
        logger.debug("IPC listen failed: %s", self._server.errorString())
        return False

    def stop(self) -> None:
        self._server.close()
        for socket in list(self._buffers):
            socket.disconnected.disconnect()
            socket.abort()
            socket.deleteLater()
        self._buffers.clear()
        QLocalServer.removeServer(self.server_name)

    def _accept_connections(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            self._buffers[socket] = bytearray()
            socket.readyRead.connect(lambda socket=socket: self._read_socket(socket))
            socket.disconnected.connect(lambda socket=socket: self._forget_socket(socket))

    def _forget_socket(self, socket: QLocalSocket) -> None:
        self._buffers.pop(socket, None)
        socket.deleteLater()

    def _read_socket(self, socket: QLocalSocket) -> None:
        buffer = self._buffers.get(socket)
        if buffer is None:
            return
        buffer.extend(socket.readAll().data())
        while b"\n" in buffer:
            raw, remainder = bytes(buffer).split(b"\n", 1)
            buffer[:] = remainder
            response = self._process_line(raw)
            socket.write((json.dumps(response) + "\n").encode("utf-8"))
            socket.flush()

    def _process_line(self, raw: bytes) -> Response:
        try:
            request = json.loads(raw.decode("utf-8"))
            if not isinstance(request, dict):
                raise ValueError("request must be a JSON object")
            return self._handler(request)
        except Exception as ex:  # The handler may fail on any request; report it to the client.
            logger.debug("IPC request failed: %s", ex)
            return {"ok": False, "error": str(ex)}


def send_request(
    request: Request,
    server_name: str = IPC_SERVER_NAME,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> Response:
    """Send one request to the running server and return its response."""
    socket = QLocalSocket()
    socket.connectToServer(server_name)
    if not socket.waitForConnected(timeout_ms):
        raise IpcUnavailable(socket.errorString())
    payload = dict(request, protocol_version=IPC_PROTOCOL_VERSION)
    socket.write((json.dumps(payload) + "\n").encode("utf-8"))
    socket.flush()
    buffer = bytearray()
    while b"\n" not in buffer:
        if not socket.waitForReadyRead(timeout_ms):
            socket.abort()
            raise IpcUnavailable(
                f"InkSim server did not respond within {timeout_ms / 1000:g} seconds"
            )
        buffer.extend(socket.readAll().data())
    socket.disconnectFromServer()
    line = bytes(buffer).split(b"\n", 1)[0]
    return json.loads(line.decode("utf-8"))
