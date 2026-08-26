"""Local JSON-line interconnect for controlling a running InkSim window."""

import json

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from .constants import IPC_SERVER_NAME


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

    def start(self):
        """Start listening, returning False when another server is active."""
        if self.server.listen(self.server_name):
            return True
        probe = QLocalSocket(self)
        probe.connectToServer(self.server_name)
        active = probe.waitForConnected(150)
        probe.abort()
        probe.deleteLater()
        if active:
            return False
        QLocalServer.removeServer(self.server_name)
        if self.server.listen(self.server_name):
            return True
        self.error.emit(self.server.errorString())
        return False

    def stop(self):
        """Stop listening and remove the local endpoint."""
        self.server.close()
        QLocalServer.removeServer(self.server_name)

    def _accept_connections(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
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
                response = self._dispatch(request)
            except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as ex:
                response = {"ok": False, "error": str(ex)}
            socket.write((json.dumps(response) + "\n").encode("utf-8"))
            socket.flush()

    def _dispatch(self, request):
        if not isinstance(request, dict):
            raise ValueError("command must be a JSON object")
        command = request.get("command")
        if command in ("open", "open_and_delete"):
            path = request.get("path")
            if not isinstance(path, str) or not path:
                raise ValueError("open requires a non-empty path")
            delete_after_load = command == "open_and_delete"
            opened = self.window.open_file(path, delete_after_load=delete_after_load)
            if not opened:
                return {"ok": False, "command": command, "path": path}
            if request.get("focus", True):
                self.window.focus_window()
            return {"ok": True, "command": command, "path": path}
        if command == "focus":
            self.window.focus_window()
            return {"ok": True, "command": "focus"}
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
    socket = QLocalSocket()
    socket.connectToServer(server_name)
    if not socket.waitForConnected(timeout):
        raise RuntimeError(f"cannot connect to InkSim server: {socket.errorString()}")
    socket.write((json.dumps(command) + "\n").encode("utf-8"))
    if not socket.waitForBytesWritten(timeout) or not socket.waitForReadyRead(timeout):
        raise RuntimeError("InkSim server did not respond")
    response = bytes(socket.readLine()).decode("utf-8").strip()
    socket.disconnectFromServer()
    return json.loads(response)