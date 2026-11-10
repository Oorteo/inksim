# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from pathlib import Path

from inksim.gui.open_dialog import OpenBrowserDialog
from inksim.integration.paths import INKSCAPE_EXTENSION_STATUS_KEY, ToolInfo, ToolStatus

_SVG = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="120" height="80">
  <rect width="120" height="80" fill="#d04a4a"/>
</svg>
"""


def _tool_status(
    inkscape: str | None = "/usr/bin/inkscape",
    inkstitch: str | None = None,
) -> ToolStatus:
    return ToolStatus(
        inkscape=ToolInfo("Inkscape", inkscape, "PATH" if inkscape else "missing"),
        inkstitch=ToolInfo("Ink/Stitch", inkstitch, "PATH" if inkstitch else "missing"),
    )


def _select_file(dialog: OpenBrowserDialog, name: str) -> None:
    for index in range(dialog.file_list.count()):
        item = dialog.file_list.item(index)
        if item.text().rstrip("/") == name:
            dialog.file_list.setCurrentRow(index)
            return
    raise AssertionError(f"{name!r} not found in {dialog.file_list.count()} rows")


def test_lists_supported_files_and_folders(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr("inksim.gui.open_dialog.detect_tools", lambda: _tool_status())
    (tmp_path / "design.svg").write_text(_SVG, encoding="utf-8")
    (tmp_path / "notes.txt").write_text("not supported", encoding="utf-8")
    (tmp_path / "subfolder").mkdir()

    dialog = OpenBrowserDialog(None, tmp_path)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.wait(30)

    labels = [
        dialog.file_list.item(index).text().rstrip("/") for index in range(dialog.file_list.count())
    ]
    assert "design.svg" in labels
    assert "subfolder" in labels
    assert "notes.txt" not in labels
    dialog.reject()


def test_filter_limits_files_to_svg(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr("inksim.gui.open_dialog.detect_tools", lambda: _tool_status())
    (tmp_path / "design.svg").write_text(_SVG, encoding="utf-8")
    (tmp_path / "notes.pes").write_bytes(b"not a real design")

    dialog = OpenBrowserDialog(None, tmp_path)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.wait(30)

    index = dialog.filter_combo.findData("svg")
    assert index >= 0
    dialog.filter_combo.setCurrentIndex(index)
    qtbot.wait(30)

    labels = [
        dialog.file_list.item(row).text().rstrip("/") for row in range(dialog.file_list.count())
    ]
    assert labels == ["design.svg"]
    dialog.reject()


def test_svg_preview_is_disabled_without_inkscape(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "inksim.gui.open_dialog.detect_tools",
        lambda: _tool_status(inkscape=None, inkstitch=None),
    )
    (tmp_path / "design.svg").write_text(_SVG, encoding="utf-8")

    dialog = OpenBrowserDialog(None, tmp_path, tmp_path / "design.svg")
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.wait(50)
    _select_file(dialog, "design.svg")

    assert not dialog.open_button.isEnabled()
    assert not dialog.edit_button.isEnabled()
    assert "Inkscape" in dialog.status_label.text()
    assert dialog.svg_caption.text()
    dialog.reject()


def test_svg_preview_and_edit_are_enabled_with_inkscape(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "inksim.gui.open_dialog.detect_tools",
        lambda: _tool_status(inkscape="/usr/bin/inkscape"),
    )
    (tmp_path / "design.svg").write_text(_SVG, encoding="utf-8")

    dialog = OpenBrowserDialog(None, tmp_path, tmp_path / "design.svg")
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.wait(50)
    _select_file(dialog, "design.svg")

    assert dialog.open_button.isEnabled()
    assert dialog.edit_button.isEnabled()
    assert "/usr/bin/inkscape" in dialog.status_label.text()
    dialog.reject()


def test_svg_preview_preserves_content_aspect_and_can_be_zoomed(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr("inksim.gui.open_dialog.detect_tools", lambda: _tool_status())
    svg_path = tmp_path / "sparse.svg"
    svg_path.write_text(
        """<svg xmlns="http://www.w3.org/2000/svg" width="300" height="100"
             viewBox="0 0 300 100">
          <rect x="10" y="10" width="40" height="40" fill="#d04a4a"/>
        </svg>""",
        encoding="utf-8",
    )

    dialog = OpenBrowserDialog(None, tmp_path, svg_path)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.wait(50)
    _select_file(dialog, "sparse.svg")

    assert dialog._svg_source is not None
    assert dialog._svg_source.width() == dialog._svg_source.height()
    initial_size = dialog.svg_label.pixmap().size()
    dialog.svg_zoom_in_button.click()
    assert dialog.svg_label.pixmap().width() > initial_size.width()
    dialog.svg_zoom_out_button.click()
    assert dialog._svg_zoom == 1.0
    assert dialog.svg_zoom_label.text() == "100%"

    dialog.reject()


def test_shows_cached_inkstitch_extension_without_starting_a_probe(qtbot, tmp_path, monkeypatch):
    from inksim.config import Config

    inkscape = tmp_path / "inkscape"
    inkscape.touch()
    extension_script = tmp_path / "extensions" / "inkstitch" / "inkstitch.py"
    extension_script.parent.mkdir(parents=True)
    extension_script.touch()
    config_path = tmp_path / "config.toml"
    config = Config(config_path)
    config.set(
        INKSCAPE_EXTENSION_STATUS_KEY,
        {
            "executable": str(inkscape.resolve()),
            "status": "found",
            "commands": [{"path": str(extension_script.resolve())}],
        },
    )
    dialog_config = Config(config_path)
    monkeypatch.setattr("inksim.gui.open_dialog.Config", lambda: dialog_config)
    monkeypatch.setattr(
        "inksim.gui.open_dialog.detect_tools",
        lambda: _tool_status(inkscape=str(inkscape)),
    )

    def unexpected_probe(*args, **kwargs):
        raise AssertionError("Opening the dialog must not start an Inkscape probe.")

    monkeypatch.setattr("inksim.gui.open_dialog.QProcess", unexpected_probe)
    dialog = OpenBrowserDialog(None, tmp_path)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.wait(30)

    assert f"Ink/Stitch extension: {extension_script.resolve()}" in dialog.status_label.text()
    assert "PATH" not in dialog.status_label.text()
    config.set(
        INKSCAPE_EXTENSION_STATUS_KEY,
        {"executable": str(inkscape.resolve()), "status": "not_found", "commands": []},
    )
    dialog.refresh_tools_button.click()
    assert "not found in Inkscape" in dialog.status_label.text()
    dialog.reject()


def test_edit_in_inkscape_launches_tagged_process(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "inksim.gui.open_dialog.detect_tools",
        lambda: _tool_status(inkscape="/usr/bin/inkscape"),
    )
    calls = []

    def fake_popen(args, **kwargs):
        calls.append((args, kwargs))
        return object()

    monkeypatch.setattr("inksim.gui.open_dialog.subprocess.Popen", fake_popen)
    svg_path = tmp_path / "design.svg"
    svg_path.write_text(_SVG, encoding="utf-8")

    dialog = OpenBrowserDialog(None, tmp_path, svg_path)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.wait(50)
    _select_file(dialog, "design.svg")
    dialog._edit_in_inkscape()

    assert calls
    args, _kwargs = calls[0]
    assert args[0] == "/usr/bin/inkscape"
    assert any(str(arg).startswith("--app-id-tag=inksim-") for arg in args)
    assert str(svg_path) in args
    assert dialog.result_action == "edit"


def test_open_embroidery_accepts_selected_file(qtbot, sample_design, monkeypatch):
    monkeypatch.setattr("inksim.gui.open_dialog.detect_tools", lambda: _tool_status())

    dialog = OpenBrowserDialog(None, sample_design.parent, sample_design)
    qtbot.addWidget(dialog)
    dialog.show()

    for _ in range(20):
        qtbot.wait(50)
        if dialog._preview_loaded:
            break

    assert dialog._preview_loaded
    dialog.open_button.click()

    assert dialog.selected_path == sample_design.resolve()
    assert dialog.result_action == "open"


def test_svg_drop_opens_new_browser(qtbot, tmp_path, monkeypatch):
    from PySide6.QtCore import QMimeData, Qt, QUrl
    from PySide6.QtGui import QDropEvent

    from inksim.gui.frame import MainWindow

    svg_path = tmp_path / "design.svg"
    svg_path.write_text(_SVG, encoding="utf-8")
    window = MainWindow(window_size=(320, 240))
    qtbot.addWidget(window)
    calls = []

    class RecordingBrowserDialog:
        def __init__(self, parent, initial_directory, selected_file=None, recent_directories=None):
            calls.append((Path(initial_directory), Path(selected_file)))

        def exec(self):
            return 0

    monkeypatch.setattr("inksim.gui.frame.OpenBrowserDialog", RecordingBrowserDialog)
    mime_data = QMimeData()
    mime_data.setUrls([QUrl.fromLocalFile(str(svg_path))])
    drop_event = QDropEvent(
        window.rect().center().toPointF(),
        Qt.CopyAction,
        mime_data,
        Qt.LeftButton,
        Qt.NoModifier,
    )

    window.dropEvent(drop_event)

    assert calls == [(tmp_path, svg_path)]
    window.close()
