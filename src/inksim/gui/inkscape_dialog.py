# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Dialog for inspecting the selected Inkscape executable and its extensions."""

from __future__ import annotations

import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
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


@dataclass(frozen=True)
class InkStitchCommand:
    inx_path: Path
    command: str
    interpreter: str
    location: str

    @property
    def resolved_path(self) -> Path:
        command_path = Path(self.command).expanduser()
        if self.location == "inx" and not command_path.is_absolute():
            command_path = self.inx_path.parent / command_path
        return command_path.resolve()


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

        layout.addWidget(QLabel(_("integration.inkstitch.heading"), self))
        self.inkstitch_combo = QComboBox(self)
        self.inkstitch_combo.currentIndexChanged.connect(self._show_inkstitch_command)
        layout.addWidget(self.inkstitch_combo)
        self.inkstitch_details_label = QLabel(self)
        self.inkstitch_details_label.setWordWrap(True)
        self.inkstitch_details_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.inkstitch_details_label)

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
        extension_paths = [
            Path(path)
            for path in (user_path, system_path)
            if path != _("integration.inkscape.directory_unavailable")
        ]
        installations = self._find_inkstitch_commands(extension_paths)
        self.inkstitch_combo.clear()
        for installation in installations:
            self.inkstitch_combo.addItem(str(installation.resolved_path), installation)
        self.inkstitch_combo.setVisible(len(installations) > 1)
        if not installations:
            self.inkstitch_details_label.setText(_("integration.inkstitch.not_found"))
        else:
            self._show_inkstitch_command(0)

    def _show_inkstitch_command(self, index: int) -> None:
        installation = self.inkstitch_combo.itemData(index)
        if not isinstance(installation, InkStitchCommand):
            return
        self.inkstitch_details_label.setText(
            "\n".join(
                (
                    _("integration.inkstitch.location").format(value=installation.location),
                    _("integration.inkstitch.interpreter").format(value=installation.interpreter),
                    _("integration.inkstitch.command").format(value=installation.command),
                    _("integration.inkstitch.resolved_path").format(
                        path=installation.resolved_path
                    ),
                )
            )
        )

    @staticmethod
    def _find_inkstitch_commands(extension_paths: list[Path]) -> list[InkStitchCommand]:
        commands: dict[Path, InkStitchCommand] = {}
        for extension_path in extension_paths:
            if not extension_path.is_dir():
                continue
            try:
                extension_directories = sorted(extension_path.iterdir())
            except OSError:
                continue
            for extension_directory in extension_directories:
                if not extension_directory.is_dir():
                    continue
                inx_directory = extension_directory / "inx"
                if not inx_directory.is_dir():
                    continue
                for inx_path in sorted(inx_directory.rglob("inkstitch*about.inx")):
                    if not inx_path.is_file() or inx_path.suffix != ".inx":
                        continue
                    try:
                        root = ET.parse(inx_path).getroot()
                    except (ET.ParseError, OSError):
                        continue
                    for element in root.iter():
                        if element.tag.rsplit("}", 1)[-1] != "command":
                            continue
                        command = (element.text or "").strip()
                        if not command:
                            continue
                        resolved_inx_path = inx_path.resolve()
                        commands[resolved_inx_path] = InkStitchCommand(
                            inx_path=resolved_inx_path,
                            command=command,
                            interpreter=element.get("interpreter", ""),
                            location=element.get("location", ""),
                        )
                        break
        return sorted(commands.values(), key=lambda item: str(item.resolved_path).casefold())

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
