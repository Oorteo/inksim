from uuid import uuid4

from PySide6.QtCore import QObject

from inksim.interconnect import InterconnectServer


class FakeWindow(QObject):
    def __init__(self):
        super().__init__()
        self.calls = []

    def open_file(self, path):
        self.calls.append(("open", path))
        return True

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
        assert server._dispatch({"command": "open", "path": "sample_design"})["ok"]
        assert server._dispatch({"command": "focus"})["ok"]
        assert server._dispatch({"command": "show", "focus": False})["ok"]
        assert server._dispatch({"command": "hide"})["ok"]
        assert server._dispatch({"command": "quit"})["ok"]
        assert window.calls == [
            ("open", "sample_design"),
            ("focus",),
            ("focus",),
            ("show", False),
            ("hide",),
            ("quit",),
        ]
    finally:
        server.stop()
