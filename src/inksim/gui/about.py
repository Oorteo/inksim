# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

"""About dialog for the InkSim application."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
)

from ..constants import APP_TITLE
from ..runtime import runtime_info_lines


def show_about(parent):
    """Show the InkSim About dialog."""
    dialog = QDialog(parent)
    dialog.setWindowTitle(f"About {APP_TITLE}")
    dialog.setWindowIcon(parent.windowIcon())
    dialog.setMinimumWidth(620)
    dialog.setStyleSheet(
        "QDialog { background: #faf8f4; }"
        "QLabel#tagline { color: #3e4752; font-size: 14px; }"
        "QLabel#body { color: #4d5560; font-size: 12px; }"
        "QPlainTextEdit { background: #ffffff; border: 1px solid #ddd6cc; "
        "border-radius: 5px; color: #39424e; font-family: monospace; "
        "padding: 8px; }"
    )

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(28, 24, 28, 20)
    layout.setSpacing(12)

    logo = QLabel(dialog)
    logo_path = Path(__file__).parent.parent / "assets" / "InkSim_colorful_small.png"
    pixmap = QPixmap(str(logo_path))
    logo.setPixmap(pixmap.scaled(180, 180, Qt.KeepAspectRatio,
                                  Qt.SmoothTransformation))
    logo.setAlignment(Qt.AlignCenter)
    layout.addWidget(logo)

    tagline = QLabel(
        "Interactive embroidery simulation, inspection, and export.", dialog
    )
    tagline.setObjectName("tagline")
    tagline.setAlignment(Qt.AlignCenter)
    layout.addWidget(tagline)

    body = QLabel(
        "Explore stitch order, thread colors, jumps, trims, and machine "
        "commands before production. Preview the design stitch by stitch, "
        "switch rendering styles, and export what you see.",
        dialog,
    )
    body.setObjectName("body")
    body.setWordWrap(True)
    body.setAlignment(Qt.AlignCenter)
    layout.addWidget(body)

    runtime = QPlainTextEdit("\n".join(runtime_info_lines()), dialog)
    runtime.setReadOnly(True)
    runtime.setFont(QFont("Monospace", 9))
    runtime.setMaximumHeight(210)
    layout.addWidget(runtime)

    buttons = QDialogButtonBox(QDialogButtonBox.Close, parent=dialog)
    buttons.rejected.connect(dialog.reject)
    buttons.accepted.connect(dialog.accept)
    layout.addWidget(buttons)
    dialog.exec()
