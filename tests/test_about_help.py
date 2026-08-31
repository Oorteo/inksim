"""Smoke tests for the About and Help dialogs."""

from inksim.gui.about import show_about
from inksim.gui.frame import MainWindow
from inksim.gui.help import show_help
from inksim.gui.settings import show_settings


def test_about_dialog_opens(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    show_about(window)


def test_help_dialog_opens(qtbot):
    viewer = MainWindow().viewer
    qtbot.addWidget(viewer)
    show_help(viewer)


def test_settings_dialog_opens(qtbot):
    viewer = MainWindow().viewer
    qtbot.addWidget(viewer)
    show_settings(viewer)
