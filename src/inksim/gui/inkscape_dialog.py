# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Dialog for inspecting the selected Inkscape executable and its extensions."""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import QProcess, Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..i18n import _

# Cold starts of Inkscape on Windows (antivirus scans, profile setup) can exceed a few seconds.
INKSCAPE_PROBE_TIMEOUT_S = 10
_WINDOWS_CREATE_NO_WINDOW = 0x08000000
_PROBE_OPTIONS = ("--user-data-directory", "--system-data-directory")


def _hide_windows_console(arguments: Any) -> None:
    arguments.flags |= _WINDOWS_CREATE_NO_WINDOW


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

        self.probe_status_label = QLabel(_("integration.inkscape.probing"), self)
        self.probe_status_label.setAlignment(Qt.AlignCenter)
        self.probe_status_label.setStyleSheet(
            "background-color: rgba(0, 0, 0, 170); color: white; border-radius: 8px; padding: 12px;"
        )
        self.probe_status_label.setVisible(False)
        layout.addWidget(self.probe_status_label)
        self._probe_process: QProcess | None = None
        self._probe_results: list[str] = []
        self._probe_executable = ""
        self._probe_timer = QTimer(self)
        self._probe_timer.setSingleShot(True)
        self._probe_timer.timeout.connect(self._on_probe_timeout)

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

        # Probe after show so the status bubble is visible while Inkscape starts.
        QTimer.singleShot(0, lambda: self._set_executable(executable))

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
        self._start_probe(executable_path)

    def done(self, result: int) -> None:
        self._cancel_probe()
        super().done(result)

    def _start_probe(self, executable_path: str) -> None:
        self._probe_executable = executable_path
        self._probe_results = []
        self._set_probing(True)
        self._run_next_probe()

    def _run_next_probe(self) -> None:
        process = QProcess(self)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        if sys.platform == "win32" and hasattr(process, "setCreateProcessArgumentsModifier"):
            # Keeps the console-subsystem inkscape.com from flashing a terminal on Windows.
            process.setCreateProcessArgumentsModifier(_hide_windows_console)
        process.finished.connect(lambda *_, p=process: self._on_probe_step_done(p))
        process.errorOccurred.connect(
            lambda *_, p=process: self._on_probe_step_done(p, failed=True)
        )
        self._probe_process = process
        self._probe_timer.start(int(INKSCAPE_PROBE_TIMEOUT_S * 1000))
        process.start(self._probe_executable, [_PROBE_OPTIONS[len(self._probe_results)]])

    def _on_probe_step_done(self, process: QProcess, failed: bool = False) -> None:
        # Ignore late signals from a process that was already replaced, killed, or handled.
        if process is not self._probe_process:
            return
        self._probe_process = None
        self._probe_timer.stop()
        output = ""
        if (
            not failed
            and process.exitStatus() == QProcess.ExitStatus.NormalExit
            and process.exitCode() == 0
        ):
            output = bytes(process.readAllStandardOutput().data()).decode(errors="replace").strip()
        process.deleteLater()
        self._probe_results.append(output)
        if output and len(self._probe_results) < len(_PROBE_OPTIONS):
            self._run_next_probe()
        else:
            # A failed query means this executable cannot answer the rest either, so do not run them.
            self._probe_results.extend([""] * (len(_PROBE_OPTIONS) - len(self._probe_results)))
            self._finish_probe(timed_out=False)

    def _on_probe_timeout(self) -> None:
        process = self._probe_process
        if process is None:
            return
        self._probe_process = None
        process.kill()
        process.deleteLater()
        self._finish_probe(timed_out=True)

    def _finish_probe(self, timed_out: bool) -> None:
        self._set_probing(False)
        if timed_out:
            # An unresponsive Inkscape will not answer the second query either, so do not wait twice.
            user_path = system_path = _("integration.inkscape.directory_unavailable")
        else:
            user_path, system_path = (
                self._extensions_directory(output) for output in self._probe_results
            )
        self._apply_extension_directories(user_path, system_path, timed_out)

    def _cancel_probe(self) -> None:
        process = self._probe_process
        if process is None:
            return
        self._probe_process = None
        self._probe_timer.stop()
        process.kill()
        process.deleteLater()
        self._set_probing(False)

    def _set_probing(self, active: bool) -> None:
        self.probe_status_label.setVisible(active)
        self.change_button.setEnabled(not active)
        if active:
            QApplication.setOverrideCursor(Qt.WaitCursor)
        else:
            QApplication.restoreOverrideCursor()

    @staticmethod
    def _extensions_directory(data_directory: str) -> str:
        if not data_directory:
            return _("integration.inkscape.directory_unavailable")
        return str(Path(data_directory).expanduser() / "extensions")

    def _apply_extension_directories(
        self, user_path: str, system_path: str, timed_out: bool
    ) -> None:
        if timed_out:
            QMessageBox.warning(
                self,
                _("integration.inkscape.title"),
                _("integration.inkscape.timeout").format(seconds=INKSCAPE_PROBE_TIMEOUT_S),
            )
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
