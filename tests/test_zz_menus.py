# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Smoke tests that every menu action can be triggered without crashing."""

import sys
import time
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from inksim.gui.frame import MainWindow


def _close_active_modal():
    dialog = QApplication.activeModalWidget()
    if dialog is not None:
        dialog.close()


def _collect_menu_actions(menu):
    """Return all leaf QAction objects under *menu*, recursing into submenus."""
    actions = []
    for action in menu.actions():
        if action.menu() is not None:
            actions.extend(_collect_menu_actions(action.menu()))
        elif not action.isSeparator():
            actions.append(action)
    return actions


def _all_frame_actions(window):
    """Return every QAction from the menu bar."""
    actions = []
    for menu in window.menuBar().findChildren(object):
        if hasattr(menu, "actions"):
            actions.extend(_collect_menu_actions(menu))
    # Deduplicate by object identity.
    seen = set()
    unique = []
    for action in actions:
        if id(action) not in seen:
            seen.add(id(action))
            unique.append(action)
    return unique


def _patch_blocking_dialogs(monkeypatch):
    """Replace modal dialogs so the test does not block on user interaction."""
    from inksim.gui.dialogs import EmbroideryOpenDialog as RealOpenDialog

    class NoopOpenDialog(RealOpenDialog):
        def exec(self):
            return 0  # QDialog.Rejected

    monkeypatch.setattr("inksim.gui.frame.EmbroideryOpenDialog", NoopOpenDialog)

    class NoopBrowserDialog:
        def __init__(self, *args, **kwargs):
            self.result_action = None
            self.preview_csv_path = None
            self.document_path = None
            self.selected_path = None

        def exec(self):
            return 0  # QDialog.Rejected

    monkeypatch.setattr("inksim.gui.frame.OpenBrowserDialog", NoopBrowserDialog)
    monkeypatch.setattr("inksim.gui.frame.QFileDialog.getSaveFileName", lambda *a, **k: ("", ""))
    monkeypatch.setattr("inksim.gui.frame.QMessageBox.critical", lambda *a, **k: None)
    monkeypatch.setattr("inksim.gui.frame.QMessageBox.information", lambda *a, **k: None)
    monkeypatch.setattr("inksim.gui.frame.QMessageBox.warning", lambda *a, **k: None)

    class NoopInkscapeDialog:
        def __init__(self, parent, executable):
            pass

        def exec(self):
            return 0

    monkeypatch.setattr("inksim.gui.frame.InkscapeIntegrationDialog", NoopInkscapeDialog)

    # The renderer picker launches a GPU preview that requires a real GL
    # context; stub it out so the menu action can be exercised safely.
    class NoopRendererDialog:
        def __init__(self, parent, selected_renderer):
            self.selected_renderer = selected_renderer

        def exec(self):
            return 0  # QDialog.Rejected

    monkeypatch.setattr("inksim.gui.renderer_picker.RendererPickerDialog", NoopRendererDialog)


def _run_menu_smoke_test(qtbot, monkeypatch, sample_design, renderer_key):
    """Create a window using *renderer_key* and trigger every menu action."""
    window = MainWindow(window_size=(320, 240))
    qtbot.addWidget(window)

    _patch_blocking_dialogs(monkeypatch)

    # The deferred fit-to-screen timer chain can outlive the test and crash
    # after Qt deletes the C++ viewer object; stub it out for the smoke test.
    monkeypatch.setattr(
        "inksim.gui.viewer.EmbroideryViewerWidget._try_fit_to_screen",
        lambda self, retries=20: None,
    )

    assert window.open_file(str(sample_design), precompute_density=False)
    window.viewer.set_renderer(renderer_key)

    failures = []
    actions = _all_frame_actions(window)

    for action in actions:
        # Close any modal dialog the previous action may have opened.
        QTimer.singleShot(0, _close_active_modal)
        try:
            action.trigger()
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{action.text()!r}: {exc}")

    assert not failures, "Failed actions:\n" + "\n".join(failures)

    # Wait for the deferred fit-to-screen timer chain to finish before the
    # window is destroyed behind its back.
    time.sleep(0.5)
    QApplication.processEvents()
    window.viewer.pan_render_timer.stop()
    window.viewer.zoom_render_timer = None
    window.viewer.play_timer.stop()
    window.close()
    QApplication.processEvents()


def test_all_menu_actions_trigger_cpu(qtbot, monkeypatch, sample_design):
    """Trigger every menu action with the default CPU renderer active."""
    _run_menu_smoke_test(qtbot, monkeypatch, sample_design, "shaded_volume")


def test_menu_mnemonics_are_omitted_for_other_locales(qtbot, monkeypatch):
    """Avoid English/Czech menu mnemonics in other localized menus."""
    monkeypatch.setattr("inksim.i18n._current_locale", "fr")
    window = MainWindow(window_size=(320, 240))
    qtbot.addWidget(window)

    menu_labels = [action.text() for action in window.menuBar().actions()]
    plain_labels = [label.replace("&", "") for label in menu_labels]

    assert "Tools" in plain_labels
    assert "Langue" in plain_labels
    assert all(
        "&" not in label for label in menu_labels if label.replace("&", "") in {"Tools", "Langue"}
    )
    window.close()


def test_locate_inkscape_shows_resolved_path(qtbot, monkeypatch):
    """Open the integration dialog with the executable found on PATH."""
    window = MainWindow(window_size=(320, 240))
    qtbot.addWidget(window)
    executables = []

    class RecordingDialog:
        def __init__(self, parent, executable):
            executables.append(executable)

        def exec(self):
            return 0

    monkeypatch.setattr("inksim.gui.frame.shutil.which", lambda name: "/opt/inkscape/bin/inkscape")
    monkeypatch.setattr("inksim.gui.frame.InkscapeIntegrationDialog", RecordingDialog)

    window._locate_inkscape_slot()

    assert executables == ["/opt/inkscape/bin/inkscape"]
    window.close()


def test_locate_inkscape_reports_missing_executable(qtbot, monkeypatch):
    """Open the integration dialog with no executable selected when missing."""
    window = MainWindow(window_size=(320, 240))
    qtbot.addWidget(window)
    executables = []

    class RecordingDialog:
        def __init__(self, parent, executable):
            executables.append(executable)

        def exec(self):
            return 0

    monkeypatch.setattr("inksim.gui.frame.shutil.which", lambda name: None)
    monkeypatch.setattr("inksim.gui.frame.InkscapeIntegrationDialog", RecordingDialog)

    window._locate_inkscape_slot()

    assert executables == [None]
    window.close()


def _wait_for_probe(qtbot, dialog):
    """Wait until the deferred extension probe has finished and hidden its status bubble."""
    qtbot.waitUntil(
        lambda: dialog.executable_label.text() != "" and dialog.probe_status_label.isHidden()
    )


def _fake_inkscape_probe(monkeypatch, data_directories=None, sleep_seconds=None):
    """Run the Inkscape probe as a real Python child process that prints the given data directories."""
    from PySide6.QtCore import QProcess

    starts = []

    class FakeInkscapeProbe(QProcess):
        def start(self, program, arguments):
            starts.append(arguments)
            if sleep_seconds is None:
                code = f"import sys; print({data_directories!r}[sys.argv[1]])"
                super().start(sys.executable, ["-c", code, *arguments])
            else:
                super().start(sys.executable, ["-c", f"import time; time.sleep({sleep_seconds})"])

    monkeypatch.setattr("inksim.gui.inkscape_dialog.QProcess", FakeInkscapeProbe)
    return starts


def test_inkscape_dialog_shows_extension_directories(qtbot, monkeypatch):
    """Display the extension directories reported by the selected executable."""
    from inksim.gui.inkscape_dialog import InkscapeIntegrationDialog

    monkeypatch.setattr("inksim.gui.inkscape_dialog.shutil.which", lambda _: None)
    monkeypatch.setattr("inksim.gui.inkscape_dialog.QMessageBox.warning", lambda *args: None)
    _fake_inkscape_probe(
        monkeypatch,
        {
            "--user-data-directory": "/home/user/.config/inkscape",
            "--system-data-directory": "/usr/share/inkscape",
        },
    )
    dialog = InkscapeIntegrationDialog(None, "/opt/inkscape/bin/inkscape")
    qtbot.addWidget(dialog)
    _wait_for_probe(qtbot, dialog)

    assert dialog.executable_label.text() == str(Path("/opt/inkscape/bin/inkscape").resolve())
    assert (
        dialog.user_extensions_label.text()
        == f"User extensions: {Path('/home/user/.config/inkscape/extensions')}"
    )
    assert (
        dialog.system_extensions_label.text()
        == f"System extensions: {Path('/usr/share/inkscape/extensions')}"
    )


def test_inkscape_dialog_change_reloads_selected_program(qtbot, monkeypatch):
    """Selecting another executable refreshes its extension directories."""
    from inksim.gui.inkscape_dialog import InkscapeIntegrationDialog

    monkeypatch.setattr("inksim.gui.inkscape_dialog.shutil.which", lambda _: None)
    monkeypatch.setattr("inksim.gui.inkscape_dialog.QMessageBox.warning", lambda *args: None)
    _fake_inkscape_probe(
        monkeypatch,
        {"--user-data-directory": "/custom/user", "--system-data-directory": "/custom/system"},
    )
    monkeypatch.setattr(
        "inksim.gui.inkscape_dialog.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: ("/custom/bin/inkscape", ""),
    )
    dialog = InkscapeIntegrationDialog(None, None)
    qtbot.addWidget(dialog)
    _wait_for_probe(qtbot, dialog)

    dialog.change_button.click()
    _wait_for_probe(qtbot, dialog)

    assert dialog.executable_label.text() == str(Path("/custom/bin/inkscape").resolve())
    assert dialog.user_extensions_label.text().endswith(str(Path("/custom/user/extensions")))
    assert dialog.system_extensions_label.text().endswith(str(Path("/custom/system/extensions")))


def test_inkstitch_command_is_discovered_from_about_inx(tmp_path, qtbot, monkeypatch):
    """Read Ink/Stitch command metadata from its about INX file."""
    import xml.etree.ElementTree as ET

    from inksim.config import Config
    from inksim.gui.inkscape_dialog import InkscapeIntegrationDialog
    from inksim.integration.paths import INKSCAPE_CONFIG_KEY

    config = Config(tmp_path / "config.toml")
    monkeypatch.setattr("inksim.gui.inkscape_dialog.Config", lambda: config)
    uvr_executable = tmp_path / "uv-tool-bin" / "uvr"
    uvr_executable.parent.mkdir()
    uvr_executable.touch()
    uvr_executable.chmod(0o755)
    monkeypatch.setattr(
        "inksim.gui.inkscape_dialog.shutil.which",
        lambda command: str(uvr_executable) if command == "uvr" else None,
    )
    user_data = tmp_path / "user-data"
    system_data = tmp_path / "system-data"
    preferences_file = user_data / "preferences.xml"
    user_data.mkdir(parents=True)
    preferences_file.write_text(
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
        "<inkscape>\n"
        "  <!--preserve comment-->\n"
        "  <group\n"
        '     id="extensions"\n'
        '     python-interpreter="python3"\n'
        '     keep="yes">\n'
        '    <param name="untouched">value</param>\n'
        "  </group>\n"
        "</inkscape>\n",
        encoding="utf-8",
    )
    original_preferences = preferences_file.read_bytes()
    inx_path = user_data / "extensions" / "inkstitch" / "inx" / "inkstitch_about.inx"
    inx_path.parent.mkdir(parents=True)
    inx_path.write_text(
        '<inkscape-extension><command location="inx" interpreter="python">'
        "../inkstitch.py</command></inkscape-extension>",
        encoding="utf-8",
    )
    ignored_inx = user_data / "extensions" / "inkstitch" / "xxx" / "inkstitch_ignored_about.inx"
    ignored_inx.parent.mkdir(parents=True)
    ignored_inx.write_text(
        '<inkscape-extension><command location="inx" interpreter="python">'
        "../ignored.py</command></inkscape-extension>",
        encoding="utf-8",
    )
    backup_inx = inx_path.parent / "inkstitch_backup_about.inx.bak"
    backup_inx.write_text(inx_path.read_text(encoding="utf-8"), encoding="utf-8")
    directory_inx = inx_path.parent / "inkstitch_directory_about.inx"
    directory_inx.mkdir()

    _fake_inkscape_probe(
        monkeypatch,
        {"--user-data-directory": str(user_data), "--system-data-directory": str(system_data)},
    )
    dialog = InkscapeIntegrationDialog(None, "/opt/inkscape/bin/inkscape")
    qtbot.addWidget(dialog)
    _wait_for_probe(qtbot, dialog)

    expected_script = (inx_path.parent / "../inkstitch.py").resolve()
    assert dialog.inkstitch_combo.isHidden()
    assert dialog.inkstitch_combo.count() == 1
    assert dialog.inkstitch_combo.itemText(0) == str(expected_script)
    assert "Location: inx" in dialog.inkstitch_details_label.text()
    assert "Interpreter: python" in dialog.inkstitch_details_label.text()
    assert "Command: ../inkstitch.py" in dialog.inkstitch_details_label.text()
    assert f"Path: {expected_script}" in dialog.inkstitch_details_label.text()
    status = config.get(INKSCAPE_CONFIG_KEY)
    assert status["status"] == "found"
    assert status["executable"] == str(Path("/opt/inkscape/bin/inkscape").resolve())
    assert status["preferences_file"] == str(preferences_file.resolve())
    assert status["python-interpretor"] == str(uvr_executable.resolve())
    assert status["active_inkstitch"] == str(inx_path.parent.resolve())
    assert str(uvr_executable.resolve()) in dialog.python_interpreter_label.text()
    assert "\n" in dialog.python_interpreter_label.text()
    assert "<!--preserve comment-->" in preferences_file.read_text(encoding="utf-8")
    preferences_root = ET.parse(preferences_file).getroot()
    preferences_group = next(
        element for element in preferences_root.iter() if element.get("id") == "extensions"
    )
    assert preferences_group.get("python-interpreter") == str(uvr_executable.resolve())
    assert preferences_group.get("keep") == "yes"
    assert preferences_group.find("param").text == "value"
    expected_preferences = original_preferences.replace(
        b'python-interpreter="python3"',
        f'python-interpreter="{uvr_executable.resolve()}"'.encode(),
        1,
    )
    assert preferences_file.read_bytes() == expected_preferences
    assert status["inkstitch"] == [
        {
            "extension_dir": str(inx_path.parent.resolve()),
            "command": "../inkstitch.py",
            "location": "inx",
            "interpreter": "python",
        }
    ]
    assert "commands" not in status
    assert "[inkscape]" in config.as_text()
    assert "[[inkscape.inkstitch]]" in config.as_text()
    assert f'python-interpretor = "{uvr_executable.resolve()}"' in config.as_text()
    assert "inkscape_extension_status" not in config.as_text()


def test_python_interpreter_is_inserted_on_its_own_line(tmp_path):
    """Insert the preference without reformatting the rest of the XML file."""
    from inksim.gui.inkscape_dialog import InkscapeIntegrationDialog

    preferences_file = tmp_path / "preferences.xml"
    preferences_file.write_bytes(
        b'<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
        b"<inkscape>\n"
        b"  <group\n"
        b'     id="extensions"\n'
        b'     python-interpreter_old="/old/uvr"\n'
        b'     keep="yes">\n'
        b"  </group>\n"
        b"</inkscape>\n"
    )
    original_preferences = preferences_file.read_bytes()
    interpreter = Path("/new/uvr")
    expected_preferences = original_preferences.replace(
        b'     keep="yes">',
        b'     keep="yes"\n     python-interpreter="/new/uvr">',
        1,
    )

    InkscapeIntegrationDialog._write_python_interpreter(preferences_file, interpreter)

    assert preferences_file.read_bytes() == expected_preferences


def test_missing_uvr_warns_without_modifying_preferences(tmp_path, qtbot, monkeypatch):
    """Recommend installing uvr but never install it or replace a different interpreter."""
    from inksim.config import Config
    from inksim.gui.inkscape_dialog import InkscapeIntegrationDialog
    from inksim.integration.paths import INKSCAPE_CONFIG_KEY

    config = Config(tmp_path / "config.toml")
    monkeypatch.setattr("inksim.gui.inkscape_dialog.Config", lambda: config)
    monkeypatch.setattr("inksim.gui.inkscape_dialog.shutil.which", lambda _: None)
    warnings = []
    monkeypatch.setattr(
        "inksim.gui.inkscape_dialog.QMessageBox.warning",
        lambda *args: warnings.append(args),
    )
    user_data = tmp_path / "user-data"
    system_data = tmp_path / "system-data"
    user_data.mkdir()
    preferences_file = user_data / "preferences.xml"
    preferences_file.write_text(
        '<inkscape><group id="extensions" python-interpreter="python3" /></inkscape>',
        encoding="utf-8",
    )
    _fake_inkscape_probe(
        monkeypatch,
        {"--user-data-directory": str(user_data), "--system-data-directory": str(system_data)},
    )

    dialog = InkscapeIntegrationDialog(None, "/opt/inkscape/bin/inkscape")
    qtbot.addWidget(dialog)
    _wait_for_probe(qtbot, dialog)

    assert len(warnings) == 1
    assert "uv tool install uvr" in warnings[0][2]
    assert "python3" in dialog.python_interpreter_label.text()
    assert InkscapeIntegrationDialog._read_python_interpreter(preferences_file) == "python3"
    assert config.get(INKSCAPE_CONFIG_KEY)["python-interpretor"] == "python3"


def test_windows_uses_uvr_gui_launcher(tmp_path, monkeypatch):
    """Choose uvr-gui on Windows to avoid opening a console for GUI extensions."""
    from inksim.gui.inkscape_dialog import InkscapeIntegrationDialog

    uvr_gui = tmp_path / "uvr-gui.exe"
    uvr_gui.touch()
    uvr_gui.chmod(0o755)
    commands = []
    monkeypatch.setattr("inksim.gui.inkscape_dialog.sys.platform", "win32")
    monkeypatch.setattr(
        "inksim.gui.inkscape_dialog.shutil.which",
        lambda command: commands.append(command) or str(uvr_gui),
    )

    assert InkscapeIntegrationDialog._find_uvr_executable(None) == uvr_gui.resolve()
    assert commands == ["uvr-gui"]


def test_inkstitch_multiple_paths_can_be_selected(tmp_path, qtbot, monkeypatch):
    """Show a combo box and update details when multiple INX files are found."""
    from inksim.config import Config
    from inksim.gui.inkscape_dialog import InkscapeIntegrationDialog
    from inksim.integration.paths import INKSCAPE_CONFIG_KEY

    config = Config(tmp_path / "config.toml")
    monkeypatch.setattr("inksim.gui.inkscape_dialog.Config", lambda: config)
    monkeypatch.setattr("inksim.gui.inkscape_dialog.shutil.which", lambda _: None)
    monkeypatch.setattr("inksim.gui.inkscape_dialog.QMessageBox.warning", lambda *args: None)
    user_data = tmp_path / "user-data"
    system_data = tmp_path / "system-data"
    inx_paths = (
        user_data / "extensions" / "inkstitch-user" / "inx" / "inkstitch_about.inx",
        system_data / "extensions" / "inkstitch-system" / "inx" / "inkstitch_alt_about.inx",
    )
    for index, inx_path in enumerate(inx_paths):
        inx_path.parent.mkdir(parents=True)
        interpreter = ' interpreter="python"' if index == 0 else ""
        inx_path.write_text(
            f'<inkscape-extension><command location="inx"{interpreter}>'
            "../inkstitch.py</command></inkscape-extension>",
            encoding="utf-8",
        )

    _fake_inkscape_probe(
        monkeypatch,
        {"--user-data-directory": str(user_data), "--system-data-directory": str(system_data)},
    )
    dialog = InkscapeIntegrationDialog(None, "/opt/inkscape/bin/inkscape")
    qtbot.addWidget(dialog)
    _wait_for_probe(qtbot, dialog)

    assert not dialog.inkstitch_combo.isHidden()
    assert dialog.inkstitch_combo.count() == 2
    default_installation = dialog.inkstitch_combo.itemData(0)
    status = config.get(INKSCAPE_CONFIG_KEY)
    assert status["active_inkstitch"] == str(default_installation.extension_dir)
    selected_installation = dialog.inkstitch_combo.itemData(1)
    dialog.inkstitch_combo.setCurrentIndex(1)
    selected_path = dialog.inkstitch_combo.currentText()
    assert f"Path: {selected_path}" in dialog.inkstitch_details_label.text()
    status = config.get(INKSCAPE_CONFIG_KEY)
    assert status["active_inkstitch"] == str(selected_installation.extension_dir)
    installation_records = {record["extension_dir"]: record for record in status["inkstitch"]}
    assert "interpreter" not in installation_records[str(inx_paths[1].parent.resolve())]


def test_inkscape_dialog_reports_unresponsive_command(qtbot, monkeypatch):
    """Show a status bubble while probing and report a stuck Inkscape once, without waiting twice."""
    from inksim.config import Config
    from inksim.gui.inkscape_dialog import InkscapeIntegrationDialog
    from inksim.integration.paths import INKSCAPE_CONFIG_KEY

    config = Config()
    monkeypatch.setattr("inksim.gui.inkscape_dialog.Config", lambda: config)
    warnings = []
    monkeypatch.setattr("inksim.gui.inkscape_dialog.INKSCAPE_PROBE_TIMEOUT_S", 0.5)
    starts = _fake_inkscape_probe(monkeypatch, sleep_seconds=30)
    monkeypatch.setattr(
        "inksim.gui.inkscape_dialog.QMessageBox.warning",
        lambda *args: warnings.append(args),
    )
    dialog = InkscapeIntegrationDialog(None, "/opt/inkscape/bin/inkscape")
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: not dialog.probe_status_label.isHidden())
    assert not dialog.change_button.isEnabled()

    _wait_for_probe(qtbot, dialog)

    assert len(starts) == 1
    assert dialog.change_button.isEnabled()
    assert len(warnings) == 1
    assert "0.5 seconds" in warnings[0][2]
    assert config.get(INKSCAPE_CONFIG_KEY)["status"] == "error"
