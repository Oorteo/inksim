# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QObject, Signal

from inksim.constants import IPC_PROTOCOL_VERSION
from inksim.server import InkSimServer


class FakeWindow(QObject):
    closed = Signal(object)
    hidden = Signal(object)
    quit_all_requested = Signal()
    restart_requested = Signal(object)

    def __init__(self):
        super().__init__()
        self.document_path = None
        self.open_file_args = None
        self.open_file_calls = []
        self.browser_dialog_args = None
        self.command_line_args = None
        self.inksim_launcher = None
        self.open_file_result = True
        self.current_file_path = None
        self.debug_script = None
        self.visible = True
        self.hide_on_close = False

    def set_document_path(self, path):
        self.document_path = path

    def check_inkscape_extension(self, launcher_path):
        self.inksim_launcher = launcher_path

    def set_command_line_args(self, arguments):
        self.command_line_args = arguments.copy()

    def announce_debug_script(self, path):
        self.debug_script = path

    def set_hide_on_close(self, enabled):
        self.hide_on_close = enabled

    def isVisible(self):
        return self.visible

    def focus_window(self):
        self.visible = True

    def has_unchanged_file(self, path, temporary_input):
        return (
            self.current_file_path == Path(path).resolve()
            and temporary_input is self.open_file_args["temporary_input"]
        )

    def open_browser_dialog(self, selected_file=None, initial_directory=None):
        self.browser_dialog_args = {
            "selected_file": selected_file,
            "initial_directory": initial_directory,
        }

    def open_file(
        self,
        path,
        delete_after_load=False,
        autoplay=False,
        temporary_input=False,
        show_error_dialog=True,
    ):
        self.open_file_calls.append(path)
        self.open_file_args = {
            "path": path,
            "delete_after_load": delete_after_load,
            "autoplay": autoplay,
            "temporary_input": temporary_input,
            "show_error_dialog": show_error_dialog,
        }
        if self.open_file_result:
            self.current_file_path = Path(path).resolve()
        return self.open_file_result

    def close(self):
        if self.hide_on_close:
            self.visible = False
            self.hidden.emit(self)
            return
        self.closed.emit(self)


def _server(qapp, idle_timeout=0, open_file_result=True):
    created = []

    def create_window(options):
        window = FakeWindow()
        window.open_file_result = open_file_result
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
        "show_error_dialog": True,
    }


def test_open_loads_svg_before_showing_browser_dialog(qapp, tmp_path):
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
    assert created[0].open_file_args == {
        "path": str(input_path),
        "delete_after_load": False,
        "autoplay": False,
        "temporary_input": False,
        "show_error_dialog": False,
    }
    assert created[0].browser_dialog_args is None


def test_open_routes_svg_to_browser_if_loading_fails(qapp, tmp_path):
    server, created = _server(qapp, open_file_result=False)
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
    assert created[0].open_file_args is not None
    assert created[0].open_file_args["show_error_dialog"] is False


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


def test_hiding_last_window_keeps_it_and_starts_idle_timer(qapp):
    server, _ = _server(qapp, idle_timeout=300)
    server._handle_request(
        {"type": "open", "protocol_version": IPC_PROTOCOL_VERSION, "new_window": True}
    )
    assert not server._idle_timer.isActive()
    window = server.windows[0]

    window.close()

    assert server.windows == [window]
    assert not window.isVisible()
    assert server._idle_timer.isActive()


def test_idle_timer_disabled_when_timeout_is_zero(qapp):
    server, _ = _server(qapp, idle_timeout=0)
    server._handle_request(
        {"type": "open", "protocol_version": IPC_PROTOCOL_VERSION, "new_window": True}
    )
    server.windows[0].close()

    assert len(server.windows) == 1
    assert not server._idle_timer.isActive()


def test_server_managed_close_hides_window_and_preserves_view_state(qtbot):
    from inksim.gui.frame import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    window.viewer.visible_count = 12
    window.set_hide_on_close(True)
    window.show()

    window.close()

    assert not window.isVisible()
    assert window.viewer.visible_count == 12
    window.focus_window()
    assert window.isVisible()
    assert window.viewer.visible_count == 12
    window.set_hide_on_close(False)
    window.close()


def test_open_reuses_hidden_window_and_unchanged_input(qapp, tmp_path):
    server, created = _server(qapp)
    input_path = tmp_path / "design.pes"
    input_path.write_bytes(b"design")
    request = {
        "type": "open",
        "protocol_version": IPC_PROTOCOL_VERSION,
        "new_window": True,
        "path": str(input_path),
    }

    response = server._handle_request(request)
    window = created[0]
    window.close()
    assert not window.isVisible()

    response = server._handle_request({**request, "new_window": False})

    assert response["ok"] is True
    assert created == [window]
    assert len(window.open_file_calls) == 1
    assert window.isVisible()
    assert not server._idle_timer.isActive()

    different_path = tmp_path / "other.pes"
    different_path.write_bytes(b"other design")
    response = server._handle_request({**request, "new_window": False, "path": str(different_path)})

    assert response["ok"] is True
    assert len(window.open_file_calls) == 2
    assert window.current_file_path == different_path.resolve()


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


def test_open_request_uses_extended_response_timeout(monkeypatch):
    from inksim import server as server_module

    calls = []
    monkeypatch.setattr(server_module, "app_version", lambda: "test")
    monkeypatch.setattr(server_module, "code_fingerprint", lambda: "current")
    monkeypatch.setattr(
        server_module,
        "_hello_or_none",
        lambda: {
            "app_version": "test",
            "code_fingerprint": "current",
            "protocol_version": IPC_PROTOCOL_VERSION,
        },
    )
    monkeypatch.setattr(
        server_module,
        "send_request",
        lambda request, **kwargs: calls.append((request, kwargs)) or {"ok": True},
    )

    server_module.forward_request({"type": "open", "path": "design.pes"})

    assert calls == [
        (
            {"type": "open", "path": "design.pes"},
            {"timeout_ms": 120_000},
        )
    ]


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
