# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Dialog for inspecting the selected Inkscape executable and its extensions."""

from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..i18n import _


class InkscapeIntegrationDialog(QDialog):
    """Display an Inkscape executable and the extension directories it uses."""

    def __init__(self, parent: QWidget | None, executable: str | None) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("integration.inkscape.title"))
        self.setMinimumWidth(620)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        program_row = QHBoxLayout()
        program_row.addWidget(QLabel(_("integration.inkscape.label"), self))
        self.executable_label = QLabel(self)
        self.executable_label.setWordWrap(True)
        self.executable_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        program_row.addWidget(self.executable_label, 1)
        self.change_button = QPushButton(_("integration.inkscape.change"), self)
        self.change_button.clicked.connect(self._choose_executable)
        program_row.addWidget(self.change_button)
        layout.addLayout(program_row)

        layout.addWidget(QLabel(_("integration.inkscape.extensions"), self))
        self.user_extensions_label = QLabel(self)
        self.system_extensions_label = QLabel(self)
        for label in (self.user_extensions_label, self.system_extensions_label):
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            layout.addWidget(label)

        buttons = QDialogButtonBox(QDialogButtonBox.Close, self)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._set_executable(executable)

    def _choose_executable(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            _("integration.inkscape.title"),
            "",
            "All files (*)",
        )
        if path:
            self._set_executable(path)

    def _set_executable(self, executable: str | None) -> None:
        if not executable:
            self.executable_label.setText(_("integration.inkscape.not_found"))
            unavailable = _("integration.inkscape.directory_unavailable")
            self.user_extensions_label.setText(
                _("integration.inkscape.user_extensions").format(path=unavailable)
            )
            self.system_extensions_label.setText(
                _("integration.inkscape.system_extensions").format(path=unavailable)
            )
            return

        executable_path = str(Path(executable).resolve())
        self.executable_label.setText(executable_path)
        user_path = self._extension_directory(executable_path, "--user-data-directory")
        system_path = self._extension_directory(executable_path, "--system-data-directory")
        self.user_extensions_label.setText(
            _("integration.inkscape.user_extensions").format(path=user_path)
        )
        self.system_extensions_label.setText(
            _("integration.inkscape.system_extensions").format(path=system_path)
        )

    @staticmethod
    def _extension_directory(executable: str, option: str) -> str:
        try:
            result = subprocess.run(
                [executable, option],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return _("integration.inkscape.directory_unavailable")

        data_directory = result.stdout.strip()
        if not data_directory:
            return _("integration.inkscape.directory_unavailable")
        return str(Path(data_directory).expanduser() / "extensions")
