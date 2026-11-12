# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtCore import QObject, Signal

from inksim.constants import IPC_PROTOCOL_VERSION
from inksim.server import InkSimServer


class FakeWindow(QObject):
    closed = Signal(object)
    quit_all_requested = Signal()
    restart_requested = Signal(object)

    def __init__(self):
        super().__init__()
        self.document_path = None
        self.open_file_args = None
        self.browser_dialog_args = None
        self.command_line_args = None
        self.inksim_launcher = None

    def set_document_path(self, path):
        self.document_path = path

    def check_inkscape_extension(self, launcher_path):
        self.inksim_launcher = launcher_path

    def set_command_line_args(self, arguments):
        self.command_line_args = arguments.copy()

    def focus_window(self):
        pass

    def open_browser_dialog(self, selected_file=None, initial_directory=None):
        self.browser_dialog_args = {
            "selected_file": selected_file,
            "initial_directory": initial_directory,
        }

    def open_file(self, path, delete_after_load=False, autoplay=False, temporary_input=False):
        self.open_file_args = {
            "path": path,
            "delete_after_load": delete_after_load,
            "autoplay": autoplay,
            "temporary_input": temporary_input,
        }
        return True

    def close(self):
        self.closed.emit(self)


def _server(qapp, idle_timeout=0):
    created = []

    def create_window(options):
        window = FakeWindow()
        created.append(window)
        return window

    server = InkSimServer(qapp, create_window, idle_timeout, server_name="inksim-test-server")
    return server, created


def test_hello_reports_protocol_and_window_count(qapp):
    server, _ = _server(qapp)
    response = server._handle_request({"type": "hello"})
    assert response["ok"] is True
    assert response["protocol_version"] == IPC_PROTOCOL_VERSION
    assert response["windows"] == 0


def test_open_rejects_index_outside_window_list(qapp):
    server, created = _server(qapp)
    server._handle_request(
        {"type": "open", "protocol_version": IPC_PROTOCOL_VERSION, "new_window": True}
    )
    assert len(created) == 1

    response = server._handle_request(
        {"type": "open", "protocol_version": IPC_PROTOCOL_VERSION, "index": 3, "path": "a.dst"}
    )
    assert response["ok"] is False
    assert len(server.windows) == 1


def test_open_forwards_temporary_input_ownership(qapp, tmp_path):
    server, created = _server(qapp)
    input_path = tmp_path / "preview.csv"
    response = server._handle_request(
        {
            "type": "open",
            "protocol_version": IPC_PROTOCOL_VERSION,
            "new_window": True,
            "path": str(input_path),
            "temporary_input": True,
        }
    )
    assert response["ok"] is True
    assert created[0].open_file_args == {
        "path": str(input_path),
        "delete_after_load": False,
        "autoplay": False,
        "temporary_input": True,
    }


def test_open_routes_svg_to_browser_dialog(qapp, tmp_path):
    server, created = _server(qapp)
    input_path = tmp_path / "design.svg"
    input_path.write_text("<svg/>", encoding="utf-8")

    response = server._handle_request(
        {
            "type": "open",
            "protocol_version": IPC_PROTOCOL_VERSION,
            "new_window": True,
            "path": str(input_path),
        }
    )

    assert response["ok"] is True
    assert created[0].browser_dialog_args == {
        "selected_file": input_path.resolve(),
        "initial_directory": None,
    }
    assert created[0].open_file_args is None


def test_open_forwards_command_line_to_window(qapp):
    server, created = _server(qapp)
    command_line = ["inksim", "--extension=preview", "--id=selection"]
    response = server._handle_request(
        {
            "type": "open",
            "protocol_version": IPC_PROTOCOL_VERSION,
            "new_window": True,
            "command_line": command_line,
        }
    )
    assert response["ok"] is True
    assert created[0].command_line_args == command_line


def test_open_schedules_inkscape_extension_check(qapp):
    server, created = _server(qapp)
    response = server._handle_request(
        {
            "type": "open",
            "protocol_version": IPC_PROTOCOL_VERSION,
            "new_window": True,
            "inksim_launcher": "/opt/inksim/bin/inksim",
        }
    )
    qapp.processEvents()

    assert response["ok"] is True
    assert created[0].inksim_launcher == "/opt/inksim/bin/inksim"


def test_closing_last_window_starts_idle_timer(qapp):
    server, _ = _server(qapp, idle_timeout=300)
    server._handle_request(
        {"type": "open", "protocol_version": IPC_PROTOCOL_VERSION, "new_window": True}
    )
    assert not server._idle_timer.isActive()

    server.windows[0].close()

    assert server.windows == []
    assert server._idle_timer.isActive()


def test_idle_timer_disabled_when_timeout_is_zero(qapp):
    server, _ = _server(qapp, idle_timeout=0)
    server._handle_request(
        {"type": "open", "protocol_version": IPC_PROTOCOL_VERSION, "new_window": True}
    )
    server.windows[0].close()

    assert not server._idle_timer.isActive()


def test_stale_code_fingerprint_replaces_running_server(monkeypatch):
    from inksim import server as server_module

    calls = []
    hello = {
        "ok": True,
        "app_version": server_module.app_version(),
        "code_fingerprint": "stale",
        "protocol_version": IPC_PROTOCOL_VERSION,
    }
    monkeypatch.setattr(server_module, "_hello_or_none", lambda: hello)
    monkeypatch.setattr(
        server_module,
        "send_request",
        lambda request, **kwargs: calls.append(request) or {"ok": True},
    )
    monkeypatch.setattr(server_module, "_wait_until_stopped", lambda timeout: None)
    monkeypatch.setattr(
        server_module,
        "spawn_detached",
        lambda args: calls.append("spawn") or SimpleNamespace(pid=123, poll=lambda: None),
    )

    server_module.forward_request({"type": "status"})
    assert calls[0] == {"type": "shutdown"}
    assert "spawn" in calls


def test_server_start_timeout_reports_child_process_state(monkeypatch):
    import pytest

    from inksim import server as server_module
    from inksim.ipc import IpcUnavailable

    class ExitedProcess:
        pid = 123

        @staticmethod
        def poll():
            return 2

    monkeypatch.setattr(server_module, "_hello_or_none", lambda: None)
    monkeypatch.setattr(server_module, "spawn_detached", lambda args: ExitedProcess())
    monkeypatch.setattr(server_module, "SERVER_START_TIMEOUT_SECONDS", 0)

    with pytest.raises(
        IpcUnavailable,
        match=r"within .* seconds \(process 123 exited with code 2\)",
    ):
        server_module.forward_request({"type": "status"})


def test_frozen_build_is_rejected_explicitly(monkeypatch):
    import pytest

    from inksim import server as server_module

    server_module.code_fingerprint.cache_clear()
    monkeypatch.setattr(server_module.sys, "frozen", True, raising=False)
    with pytest.raises(NotImplementedError):
        server_module.code_fingerprint()
    server_module.code_fingerprint.cache_clear()
