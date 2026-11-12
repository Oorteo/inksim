# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import json
import sys
from pathlib import Path

from inksim.gui.open_dialog import OpenBrowserDialog
from inksim.integration.paths import INKSCAPE_CONFIG_KEY, ToolInfo, ToolStatus

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
    assert ".." in labels
    assert "notes.txt" not in labels
    dialog.reject()


def test_browser_dialog_navigates_directories_with_arrow_keys(qtbot, tmp_path, monkeypatch):
    from PySide6.QtCore import Qt

    monkeypatch.setattr("inksim.gui.open_dialog.detect_tools", lambda: _tool_status())
    subdirectory = tmp_path / "designs"
    subdirectory.mkdir()
    (subdirectory / "nested.svg").write_text(_SVG, encoding="utf-8")

    dialog = OpenBrowserDialog(None, tmp_path)
    qtbot.addWidget(dialog)
    dialog.show()

    folder_row = next(
        row
        for row in range(dialog.file_list.count())
        if dialog.file_list.item(row).text() == "designs/"
    )
    dialog.file_list.setCurrentRow(folder_row)
    qtbot.keyClick(dialog.file_list, Qt.Key.Key_Return)
    assert dialog.current_directory == tmp_path

    qtbot.keyClick(dialog.file_list, Qt.Key.Key_Right)
    assert dialog.current_directory == subdirectory
    assert dialog.file_list.item(dialog.file_list.currentRow()).text() == ".."
    parent_row = next(
        row for row in range(dialog.file_list.count()) if dialog.file_list.item(row).text() == ".."
    )
    assert dialog.file_list.currentRow() == parent_row
    qtbot.keyClick(dialog.file_list, Qt.Key.Key_Right)
    assert dialog.current_directory == tmp_path
    assert dialog.file_list.item(dialog.file_list.currentRow()).text() == "designs/"

    folder_row = next(
        row
        for row in range(dialog.file_list.count())
        if dialog.file_list.item(row).text() == "designs/"
    )
    dialog.file_list.setCurrentRow(folder_row)
    qtbot.keyClick(dialog.file_list, Qt.Key.Key_Right)
    assert dialog.current_directory == subdirectory
    qtbot.keyClick(dialog.file_list, Qt.Key.Key_Left)
    assert dialog.current_directory == tmp_path
    dialog.reject()


def test_path_editor_navigates_to_typed_directory(qtbot, tmp_path, monkeypatch):
    from PySide6.QtCore import Qt

    monkeypatch.setattr("inksim.gui.open_dialog.detect_tools", lambda: _tool_status())
    target = tmp_path / "custom location"
    target.mkdir()

    dialog = OpenBrowserDialog(None, tmp_path)
    qtbot.addWidget(dialog)
    dialog.show()

    assert not hasattr(dialog, "directory_combo")
    dialog.edit_path_button.click()
    assert dialog.path_stack.currentWidget() is dialog.path_editor_page
    dialog.path_entry.setText(str(target))
    qtbot.keyClick(dialog.path_entry, Qt.Key.Key_Return)
    assert dialog.current_directory == target
    assert dialog.path_stack.currentWidget() is dialog.breadcrumb_scroll

    dialog.edit_path_button.click()
    dialog.path_entry.setText(str(tmp_path / "missing"))
    dialog.path_go_button.click()
    assert dialog.current_directory == target
    assert dialog.path_stack.currentWidget() is dialog.path_editor_page
    dialog.edit_path_button.click()
    assert dialog.path_stack.currentWidget() is dialog.breadcrumb_scroll
    dialog.reject()


def test_places_breadcrumbs_and_favorite_directories(qtbot, tmp_path, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QPushButton

    from inksim.config import Config

    favorite = tmp_path / "favorite"
    favorite.mkdir()
    nested = favorite / "nested"
    nested.mkdir()
    config = Config(tmp_path / "config.toml")
    monkeypatch.setattr("inksim.gui.open_dialog.Config", lambda: config)
    monkeypatch.setattr("inksim.gui.open_dialog.detect_tools", lambda: _tool_status())

    launch_directory = Path.cwd().resolve()
    dialog = OpenBrowserDialog(None, tmp_path)
    qtbot.addWidget(dialog)
    launch_place = next(
        dialog.places_list.item(index)
        for index in range(dialog.places_list.count())
        if dialog.places_list.item(index).data(Qt.ItemDataRole.UserRole) == str(launch_directory)
    )
    assert launch_place.text() == launch_directory.name or launch_place.text() == str(
        launch_directory
    )
    dialog.show()
    dialog.set_directory(nested)
    qtbot.wait(10)
    assert any(
        dialog.places_list.item(index).data(Qt.ItemDataRole.UserRole) == str(launch_directory)
        and dialog.places_list.item(index).text() == launch_place.text()
        for index in range(dialog.places_list.count())
    )

    buttons = {
        button.text(): button for button in dialog.breadcrumb_widget.findChildren(QPushButton)
    }
    breadcrumb = buttons["favorite"]
    assert buttons["favorite"].width() > buttons["nested"].width()
    breadcrumb.click()
    assert dialog.current_directory == favorite

    dialog.set_directory(nested)
    dialog.add_favorite_button.click()
    assert config.get("favorite_directories") == [str(nested)]
    favorite_item = next(
        item
        for index in range(dialog.places_list.count())
        if (item := dialog.places_list.item(index)).data(Qt.ItemDataRole.UserRole + 1)
    )
    dialog.places_list.setCurrentItem(favorite_item)
    assert dialog.current_directory == nested
    dialog.remove_favorite_button.click()
    assert config.get("favorite_directories") == []
    assert dialog.remove_favorite_button.isEnabled() is False
    dialog.reject()


def test_embroidery_preview_waits_for_selection_to_settle(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr("inksim.gui.open_dialog.detect_tools", lambda: _tool_status())
    for name in ("first.pes", "second.pes", "third.pes"):
        (tmp_path / name).touch()

    dialog = OpenBrowserDialog(None, tmp_path)
    qtbot.addWidget(dialog)
    loaded_paths = []
    monkeypatch.setattr(
        dialog.preview,
        "load_design",
        lambda path, **_kwargs: loaded_paths.append(path) or True,
    )
    dialog.show()

    _select_file(dialog, "second.pes")
    _select_file(dialog, "third.pes")
    qtbot.wait(100)
    assert loaded_paths == []
    qtbot.waitUntil(lambda: len(loaded_paths) == 1)
    assert loaded_paths == [str(tmp_path / "third.pes")]
    dialog.reject()


def test_invalid_embroidery_preview_shows_message(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr("inksim.gui.open_dialog.detect_tools", lambda: _tool_status())
    bad_json = tmp_path / "not_embroidery.json"
    bad_json.write_text('{"foo": "bar"}', encoding="utf-8")

    dialog = OpenBrowserDialog(None, tmp_path)
    qtbot.addWidget(dialog)
    dialog.show()
    _select_file(dialog, bad_json.name)

    qtbot.waitUntil(
        lambda: dialog.preview_stack.currentWidget() == dialog.message_page,
        timeout=5000,
    )
    assert "Not a valid embroidery file" in dialog.message_label.text()
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
    assert labels == ["..", "design.svg"]
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


def test_svg_edit_is_enabled_with_inkscape_without_active_inkstitch(qtbot, tmp_path, monkeypatch):
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

    assert not dialog.open_button.isEnabled()
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
    assert dialog.preview_controls.isVisible()
    dialog.zoom_in_button.click()
    assert dialog.svg_preview.zoom > 1.0
    dialog.zoom_out_button.click()
    assert dialog.svg_preview.zoom == 1.0
    dialog.zoom_in_button.click()
    dialog.fit_button.click()
    assert dialog.svg_preview.zoom == 1.0

    dialog.reject()


def test_svg_preview_mouse_wheel_zoom_and_drag_pan(qtbot, tmp_path, monkeypatch):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QMouseEvent, QWheelEvent

    monkeypatch.setattr("inksim.gui.open_dialog.detect_tools", lambda: _tool_status())
    svg_path = tmp_path / "design.svg"
    svg_path.write_text(_SVG, encoding="utf-8")

    dialog = OpenBrowserDialog(None, tmp_path, svg_path)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.wait(50)
    _select_file(dialog, "design.svg")
    canvas = dialog.svg_preview
    assert canvas.zoom == 1.0

    wheel_event = QWheelEvent(
        QPoint(100, 100),
        QPoint(100, 100),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.NoButton,
        Qt.NoModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )
    canvas.wheelEvent(wheel_event)
    assert canvas.zoom > 1.0

    start_pan = canvas.pan

    def mouse_event(event_type, x, y, button, buttons):
        local_position = QPointF(x, y)
        global_position = QPointF(canvas.mapToGlobal(QPoint(x, y)))
        return QMouseEvent(
            event_type,
            local_position,
            local_position,
            global_position,
            button,
            buttons,
            Qt.KeyboardModifier.NoModifier,
        )

    canvas.mousePressEvent(
        mouse_event(
            QMouseEvent.Type.MouseButtonPress,
            100,
            100,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
        )
    )
    canvas.mouseMoveEvent(
        mouse_event(
            QMouseEvent.Type.MouseMove,
            120,
            130,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
        )
    )
    canvas.mouseReleaseEvent(
        mouse_event(
            QMouseEvent.Type.MouseButtonRelease,
            120,
            130,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
        )
    )
    assert abs(canvas.pan.x() - (start_pan.x() + 20)) < 1e-6
    assert abs(canvas.pan.y() - (start_pan.y() + 30)) < 1e-6

    dialog.fit_button.click()
    assert canvas.zoom == 1.0
    assert canvas.pan == QPointF()
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
        INKSCAPE_CONFIG_KEY,
        {
            "executable": str(inkscape.resolve()),
            "status": "found",
            "inkstitch": [
                {"extension_dir": str(extension_script.parent.resolve())},
                {"extension_dir": str(tmp_path / "extensions" / "inkstitch-other")},
            ],
            "active_inkstitch": str(extension_script.parent.resolve()),
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

    assert (
        f"Ink/Stitch extension: {extension_script.parent.resolve()}" in dialog.status_label.text()
    )
    assert str(tmp_path / "extensions" / "inkstitch-other") not in dialog.status_label.text()
    assert "PATH" not in dialog.status_label.text()

    class FakeIntegrationDialog:
        def __init__(self, parent, executable):
            pass

        def exec(self):
            config.set(
                INKSCAPE_CONFIG_KEY,
                {"executable": str(inkscape.resolve()), "status": "not_found", "inkstitch": []},
            )

    monkeypatch.setattr("inksim.gui.open_dialog.InkscapeIntegrationDialog", FakeIntegrationDialog)
    dialog.tools_button.click()
    assert "not found in Inkscape" in dialog.status_label.text()
    dialog.reject()


def test_preview_runs_active_inkstitch_directly_and_saves_output_streams(
    qtbot, tmp_path, monkeypatch
):
    from inksim.config import Config

    script = tmp_path / "extensions" / "inkstitch" / "inkstitch.py"
    script.parent.mkdir(parents=True)
    script.write_text(
        "import json, os, sys, time\n"
        "time.sleep(0.2)\n"
        "sys.stdout.write('csv-data')\n"
        "sys.stderr.write(json.dumps({\n"
        "  'arguments': sys.argv[1:],\n"
        "  'cwd': os.getcwd(),\n"
        "  'environment': {key: os.environ.get(key) for key in (\n"
        "    'INKSTITCH_OFFLINE_SCRIPT', 'INKEX_GETTEXT_DOMAIN',\n"
        "    'INKEX_GETTEXT_DIRECTORY', 'INKSCAPE_PROFILE_DIR',\n"
        "    'DOCUMENT_PATH', 'PYTHONPATH',\n"
        "  )},\n"
        "}))\n",
        encoding="utf-8",
    )
    inx_directory = script.parent / "inx"
    inx_directory.mkdir()
    locale_directory = inx_directory / "locale"
    locale_directory.mkdir()
    profile_directory = tmp_path / "inkscape-profile"
    profile_directory.mkdir()
    preferences_file = profile_directory / "preferences.xml"
    svg_path = tmp_path / "input design.svg"
    svg_path.write_text(_SVG, encoding="utf-8")
    config_path = tmp_path / "config.toml"
    config = Config(config_path)
    config.set(
        INKSCAPE_CONFIG_KEY,
        {
            "status": "found",
            "active_inkstitch": str(inx_directory),
            "preferences_file": str(preferences_file),
            "inkstitch": [
                {
                    "extension_dir": str(inx_directory),
                    "command": "../inkstitch.py",
                    "location": "inx",
                    "interpreter": "python",
                }
            ],
            "python-interpretor": sys.executable,
        },
    )
    monkeypatch.setattr("inksim.gui.open_dialog.Config", lambda: Config(config_path))
    monkeypatch.setattr("inksim.gui.open_dialog.detect_tools", lambda: _tool_status(inkscape=None))

    dialog = OpenBrowserDialog(None, tmp_path, svg_path)
    qtbot.addWidget(dialog)
    dialog.show()
    _select_file(dialog, svg_path.name)

    assert dialog.open_button.isEnabled()
    dialog.open_button.click()

    assert dialog.progress.isVisible()
    assert dialog.progress.value() == 0
    assert dialog.progress.maximum() == 100
    assert dialog.activity_label.isVisible()
    qtbot.waitUntil(lambda: dialog.result_action == "preview", timeout=5000)
    assert dialog.progress.value() == 100
    csv_path = dialog.preview_csv_path
    assert csv_path is not None
    assert csv_path.name.startswith("inksim-preview-")
    assert csv_path.suffix == ".csv"
    assert csv_path.read_text(encoding="utf-8") == "csv-data"
    assert not (tmp_path / "output.csv").exists()
    process_details = json.loads((tmp_path / "output.err").read_text(encoding="utf-8"))
    assert process_details == {
        "arguments": [
            "--extension=output",
            "--format=csv",
            "--skip_palette=true",
            str(svg_path),
        ],
        "cwd": str(script.parent),
        "environment": {
            "INKSTITCH_OFFLINE_SCRIPT": "True",
            "INKEX_GETTEXT_DOMAIN": "inkstitch",
            "INKEX_GETTEXT_DIRECTORY": str(locale_directory),
            "INKSCAPE_PROFILE_DIR": str(profile_directory),
            "DOCUMENT_PATH": "",
            "PYTHONPATH": None,
        },
    }
    csv_path.unlink()


def test_svg_preview_progress_uses_bounded_average_and_records_runs(qtbot, tmp_path, monkeypatch):
    from inksim.config import Config

    config = Config(tmp_path / "config.toml")
    monkeypatch.setattr("inksim.gui.open_dialog.Config", lambda: config)
    monkeypatch.setattr("inksim.gui.open_dialog.detect_tools", lambda: _tool_status())

    dialog = OpenBrowserDialog(None, tmp_path)
    qtbot.addWidget(dialog)
    assert dialog._get_conversion_estimate() == 10.0
    assert dialog.progress.minimum() == 0
    assert dialog.progress.maximum() == 100

    config.set("svg_preview_timing", {"total_seconds": 8.0, "count": 1})
    assert dialog._get_conversion_estimate() == 10.0
    config.set("svg_preview_timing", {"total_seconds": 200.0, "count": 2})
    dialog._conversion_estimate_seconds = dialog._get_conversion_estimate()
    assert dialog._conversion_estimate_seconds == 60.0

    monkeypatch.setattr("inksim.gui.open_dialog.time.monotonic", lambda: 200.0)
    dialog._conversion_started_at = 100.0
    dialog._update_conversion_progress()
    assert dialog.progress.value() == 99

    monkeypatch.setattr("inksim.gui.open_dialog.time.monotonic", lambda: 112.0)
    dialog._conversion_started_at = 100.0
    dialog._record_conversion_duration()
    assert config.get("svg_preview_timing") == {"total_seconds": 212.0, "count": 3}
    assert dialog._get_conversion_estimate() == 60.0
    dialog.reject()


def test_temporary_preview_input_is_removed_on_replacement_or_close(qtbot, tmp_path, monkeypatch):
    import numpy as np

    from inksim.gui.frame import MainWindow

    first_path = tmp_path / "first.csv"
    second_path = tmp_path / "second.csv"
    failed_path = tmp_path / "failed.csv"
    for path in (first_path, second_path, failed_path):
        path.write_text("csv-data", encoding="utf-8")

    window = MainWindow(window_size=(320, 240))
    qtbot.addWidget(window)
    monkeypatch.setattr(window.viewer, "load_design", lambda *args, **kwargs: True)
    monkeypatch.setattr(window.viewer, "stitches_np", np.empty((0, 2)), raising=False)
    monkeypatch.setattr(window.viewer, "invalidate_cache", lambda: None)
    monkeypatch.setattr(window.viewer, "update", lambda: None)
    monkeypatch.setattr(window, "_design_size_text", lambda: "0 x 0")
    monkeypatch.setattr(window, "refresh_command_panel", lambda: None)

    assert window.open_file(first_path, temporary_input=True)
    assert window._temporary_input_path == first_path.resolve()
    assert window.open_file(second_path, temporary_input=True)
    assert not first_path.exists()
    assert second_path.exists()

    monkeypatch.setattr(window.viewer, "load_design", lambda *args, **kwargs: False)
    assert not window.open_file(failed_path, temporary_input=True)
    assert not failed_path.exists()
    assert second_path.exists()

    window.close()
    assert not second_path.exists()


def test_temporary_preview_input_survives_language_restart(qtbot, tmp_path):
    from inksim.gui.frame import MainWindow

    input_path = tmp_path / "preview.csv"
    input_path.write_text("csv-data", encoding="utf-8")
    window = MainWindow(window_size=(320, 240))
    qtbot.addWidget(window)
    window.current_file_path = input_path.resolve()
    window._temporary_input_path = input_path.resolve()
    restart_arguments = []
    window.restart_requested.connect(restart_arguments.append)

    window._apply_language_change()

    assert restart_arguments == [["--temporary-input", str(input_path.resolve())]]
    window.close()
    assert input_path.exists()
    input_path.unlink()


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
    assert dialog.preview_controls.isVisible()
    fit_zoom = dialog.preview.zoom
    dialog.zoom_in_button.click()
    assert dialog.preview.zoom > fit_zoom
    dialog.fit_button.click()
    assert abs(dialog.preview.zoom - fit_zoom) < 0.001
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
    open_calls = []
    monkeypatch.setattr(
        window,
        "open_file",
        lambda path, show_error_dialog=True: (
            open_calls.append((Path(path), show_error_dialog)) or False
        ),
    )

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
    assert open_calls == [(svg_path, False)]
    window.close()


def test_directory_drop_opens_browser_in_dropped_directory(qtbot, tmp_path, monkeypatch):
    from PySide6.QtCore import QMimeData, Qt, QUrl
    from PySide6.QtGui import QDropEvent

    from inksim.gui.frame import MainWindow

    dropped_directory = tmp_path / "designs"
    dropped_directory.mkdir()
    window = MainWindow(window_size=(320, 240))
    qtbot.addWidget(window)
    calls = []
    monkeypatch.setattr(
        window,
        "open_browser_dialog",
        lambda checked=False, selected_file=None, initial_directory=None: calls.append(
            (selected_file, Path(initial_directory))
        ),
    )

    mime_data = QMimeData()
    mime_data.setUrls([QUrl.fromLocalFile(str(dropped_directory))])
    drop_event = QDropEvent(
        window.rect().center().toPointF(),
        Qt.CopyAction,
        mime_data,
        Qt.LeftButton,
        Qt.NoModifier,
    )

    window.dropEvent(drop_event)

    assert calls == [(None, dropped_directory)]
    window.close()
