# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Markdown help content for the InkSim viewer."""

import io

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTextEdit, QVBoxLayout

HELP_SECTIONS = (
    ("Mouse", """

| Action | Result |
| --- | --- |
| Wheel | Zoom |
| Alt or Ctrl + Wheel | Move by one stitch |
| Drag | Pan |
| Double-click design | Seek to visible stitch |
| W / A / S / D | Pan up / left / down / right |
| Click timeline | Seek stitch |
"""),
    ("Playback", """

| Key | Result |
| --- | --- |
| Right / Left | Seek by step, or switch playback direction while playing |
| Alt + Right / Left | Move by one stitch |
| Shift + Right / Left | Next or previous command |
| Ctrl + Right / Left | Next or previous color |
| Up / Down | Adjust playback speed while playing |
| Home / End | First or last stitch |
| Space | Play or pause |
| Esc | Finish playback directionally (forward → full design, backward → hide all) |
"""),
    ("View", """

| Key | Result |
| --- | --- |
| C | Center design |
| F | Fit design to window |
| Ctrl + A | Toggle show all / show no stitches |
| F11 | Fullscreen |
| M | Toggle snap / normal view |
| 1 | Physical 1:1 size |
| V | Toggle embroidery |
| G | Toggle grid |
| N | Toggle needle |
| J | Cycle jumps: off, all, risky only |
| X | Toggle density map |
| Z | Toggle realistic rendering |
| R | Choose stitch renderer |
| H | Toggle help |
| I | Toggle settings |
"""),
    ("Rendering", """

| Key | Result |
| --- | --- |
| [ / ] | Change thread width |
| Ctrl + [ / ] | Adjust dark shading |
| Alt + [ / ] | Adjust light shading |
| + / - | Zoom |
"""),
)


def show_help(viewer):
    """Show the viewer help dialog."""
    viewer._show_markdown_columns_dialog(
        "help_dialog",
        "Help - InkSim",
        HELP_SECTIONS,
        columns=4,
        width=1400,
        height=650,
    )


def show_command_line_help(parent):
    """Show a read-only dialog with the inksim command-line help text."""
    from ..cli import build_argument_parser

    parser = build_argument_parser()
    help_stream = io.StringIO()
    parser.print_help(help_stream)
    help_text = help_stream.getvalue()

    dialog = QDialog(parent)
    dialog.setWindowTitle("Command line options - InkSim")
    dialog.resize(900, 700)

    layout = QVBoxLayout(dialog)
    text_edit = QTextEdit(dialog)
    text_edit.setReadOnly(True)
    text_edit.setPlainText(help_text)
    text_edit.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
    layout.addWidget(text_edit)

    buttons = QDialogButtonBox(QDialogButtonBox.Ok)
    buttons.accepted.connect(dialog.accept)
    layout.addWidget(buttons)

    dialog.exec()
