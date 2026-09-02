# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Smoke tests for the About and Help dialogs."""

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from inksim.gui.about import show_about
from inksim.gui.frame import MainWindow
from inksim.gui.help import show_help
from inksim.gui.settings import show_settings


def _close_active_modal():
    dialog = QApplication.activeModalWidget()
    if dialog is not None:
        dialog.close()


def test_about_dialog_opens(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    QTimer.singleShot(0, _close_active_modal)
    show_about(window)


def test_help_dialog_opens(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    show_help(window.viewer)
    assert window.viewer.help_dialog is not None
    window.viewer.help_dialog.close()


def test_settings_dialog_opens(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    show_settings(window.viewer)
    assert window.viewer.settings_dialog is not None
    window.viewer.settings_dialog.close()
