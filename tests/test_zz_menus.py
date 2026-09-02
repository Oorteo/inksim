# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Smoke tests that every menu action can be triggered without crashing."""

import time

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
    monkeypatch.setattr("inksim.gui.frame.QFileDialog.getSaveFileName", lambda *a, **k: ("", ""))
    monkeypatch.setattr("inksim.gui.frame.QMessageBox.critical", lambda *a, **k: None)
    monkeypatch.setattr("inksim.gui.frame.QMessageBox.information", lambda *a, **k: None)
    monkeypatch.setattr("inksim.gui.frame.QMessageBox.warning", lambda *a, **k: None)

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
