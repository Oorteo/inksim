# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

from uuid import uuid4

from PySide6.QtCore import QObject

from inksim.interconnect import InterconnectServer


class FakeWindow(QObject):
    def __init__(self):
        super().__init__()
        self.calls = []
        self.last_directory = None

    def open_file(self, path, delete_after_load=False, autoplay=False):
        self.calls.append(("open", path, delete_after_load, autoplay))
        return True

    def set_document_path(self, path):
        self.calls.append(("document", path))
        self.last_directory = str(path.parent)

    def focus_window(self):
        self.calls.append(("focus",))

    def show_window(self, focus=True):
        self.calls.append(("show", focus))

    def hide(self):
        self.calls.append(("hide",))

    def request_quit(self):
        self.calls.append(("quit",))


def test_interconnect_dispatches_local_commands(qapp):
    window = FakeWindow()
    server = InterconnectServer(window, f"inksim-test-{uuid4().hex}")
    assert server.start()
    try:
        token = server.auth_token

        def dispatch(request):
            request = {"auth_token": token, **request}
            return server._dispatch(request)

        assert dispatch({"command": "open", "path": "sample_design"})["ok"]
        assert dispatch({"command": "focus"})["ok"]
        assert dispatch({"command": "show", "focus": False})["ok"]
        assert dispatch({"command": "hide"})["ok"]
        assert dispatch({"command": "quit"})["ok"]
        assert window.calls == [
            ("open", "sample_design", False, False),
            ("focus",),
            ("focus",),
            ("show", False),
            ("hide",),
            ("quit",),
        ]
    finally:
        server.stop()


def test_open_and_delete_preserves_document_path_for_save_as(qapp, tmp_path):
    document_path = tmp_path / "KL.svg"
    window = FakeWindow()
    server = InterconnectServer(window, f"inksim-test-{uuid4().hex}")

    response = server._dispatch({
        "auth_token": server.auth_token,
        "command": "open_and_delete",
        "path": "/tmp/transient.csv",
        "document_path": str(document_path),
    })

    assert response["ok"]
    assert window.calls == [
        ("document", document_path),
        ("open", "/tmp/transient.csv", True, False),
        ("focus",),
    ]
