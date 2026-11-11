# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Dialog for inspecting the selected Inkscape executable and its extensions."""

from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.parsers import expat
from xml.sax.saxutils import escape as escape_xml_attribute

from filelock import Timeout
from PySide6.QtCore import QProcess, Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..config import Config
from ..i18n import _
from ..integration.inkscape_extensions import (
    INSTALL_DIRECTORY,
    InstalledInkSimExtension,
    InstallPlan,
    InstallSafetyError,
    find_installed_inksim_extensions,
    install_extension,
    list_inksim_extension_files,
    prepare_install,
    remove_old_inksim_extension,
    resolve_inksim_launcher,
)
from ..integration.paths import INKSCAPE_CONFIG_KEY
from ..paths import _sanitize_path_text

# Cold starts of Inkscape on Windows (antivirus scans, profile setup) can exceed a few seconds.
INKSCAPE_PROBE_TIMEOUT_S = 10
_WINDOWS_CREATE_NO_WINDOW = 0x08000000
_PROBE_OPTIONS = ("--user-data-directory", "--system-data-directory")
_VERSION_PROBE_OPTION = "--version"


def _hide_windows_console(arguments: Any) -> None:
    arguments.flags |= _WINDOWS_CREATE_NO_WINDOW


@dataclass(frozen=True)
class InkStitchInstallation:
    inx_path: Path
    command: str
    interpreter: str | None
    location: str

    @property
    def extension_dir(self) -> Path:
        """Return the directory used to resolve an INX-relative command."""
        return self.inx_path.parent

    @property
    def resolved_path(self) -> Path:
        command_path = Path(self.command).expanduser()
        if self.location == "inx" and not command_path.is_absolute():
            command_path = self.extension_dir / command_path
        return command_path.resolve()


class InkscapeIntegrationDialog(QDialog):
    """Display an Inkscape executable and the extension directories it uses."""

    def __init__(self, parent: QWidget | None, executable: str | None) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("integration.inkscape.title"))
        self.resize(860, 800)
        self.setMinimumSize(720, 640)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 14)
        layout.setSpacing(12)

        def create_section(title_key: str, object_name: str) -> tuple[QGroupBox, QVBoxLayout]:
            title = _(title_key)
            group = QGroupBox(self)
            group.setObjectName(object_name)
            group.setAccessibleName(title)
            section_layout = QVBoxLayout(group)
            heading = QLabel(title, group)
            heading.setObjectName(f"{object_name}Title")
            heading_font = heading.font()
            heading_font.setBold(True)
            heading.setFont(heading_font)
            section_layout.addWidget(heading)
            return group, section_layout

        self.probe_status_label = QLabel(_("integration.inkscape.probing"), self)
        self.probe_status_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.probe_status_label.setStyleSheet("padding: 6px 8px;")
        self.probe_status_label.setVisible(False)
        layout.addWidget(self.probe_status_label)
        self._probe_process: QProcess | None = None
        self._probe_results: list[str] = []
        self._probe_version: str | None = None
        self._probe_executable = ""
        self._probe_error: str | None = None
        self._inkscape_extension_roots: tuple[tuple[Path, bool], ...] = ()
        self._installed_inksim_extensions: tuple[InstalledInkSimExtension, ...] = ()
        self._probe_timer = QTimer(self)
        self._probe_timer.setSingleShot(True)
        self._probe_timer.timeout.connect(self._on_probe_timeout)
        self._report_entries: list[str] = []

        application_group, application_layout = create_section(
            "integration.inkscape.section.application", "applicationSection"
        )
        program_row = QHBoxLayout()
        self.executable_label = QLabel(self)
        self.executable_label.setWordWrap(True)
        self.executable_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        program_row.addWidget(self.executable_label, 1)
        self.change_button = QPushButton(_("integration.inkscape.change"), self)
        self.change_button.clicked.connect(self._choose_executable)
        program_row.addWidget(self.change_button)
        program_details = QHBoxLayout()
        program_details.addWidget(QLabel(_("integration.inkscape.label"), self))
        program_details.addLayout(program_row, 1)
        application_layout.addLayout(program_details)
        self.version_label = QLabel(
            _("integration.inkscape.version").format(
                version=_("integration.inkscape.version_unavailable")
            ),
            self,
        )
        self.version_label.setWordWrap(True)
        self.version_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        application_layout.addWidget(self.version_label)
        layout.addWidget(application_group)

        extensions_group, extensions_layout = create_section(
            "integration.inkscape.section.extensions", "extensionsSection"
        )
        self._user_extensions_directory: Path | None = None
        self.user_extensions_label = QLabel(self)
        self.system_extensions_label = QLabel(self)
        for label in (self.user_extensions_label, self.system_extensions_label):
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            extensions_layout.addWidget(label)
        self.python_interpreter_label = QLabel(self)
        self.python_interpreter_label.setWordWrap(True)
        self.python_interpreter_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        extensions_layout.addWidget(self.python_interpreter_label)
        self._show_python_interpreter(None)
        layout.addWidget(extensions_group)

        inkstitch_group, inkstitch_layout = create_section(
            "integration.inkscape.section.inkstitch", "inkstitchSection"
        )
        self.inkstitch_combo = QComboBox(self)
        self.inkstitch_combo.currentIndexChanged.connect(self._show_inkstitch_command)
        inkstitch_layout.addWidget(self.inkstitch_combo)
        self.inkstitch_details_label = QLabel(self)
        self.inkstitch_details_label.setWordWrap(True)
        self.inkstitch_details_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        inkstitch_layout.addWidget(self.inkstitch_details_label)
        layout.addWidget(inkstitch_group)

        inksim_group, inksim_layout = create_section(
            "integration.inkscape.section.inksim", "inksimSection"
        )
        self.inksim_extensions_list = QPlainTextEdit(self)
        self.inksim_extensions_list.setObjectName("inksimExtensionDirectories")
        self.inksim_extensions_list.setReadOnly(True)
        self.inksim_extensions_list.setFixedHeight(
            self.inksim_extensions_list.fontMetrics().lineSpacing() * 3
            + round(2 * self.inksim_extensions_list.document().documentMargin())
            + 2 * self.inksim_extensions_list.frameWidth()
        )
        inksim_layout.addWidget(self.inksim_extensions_list)
        inksim_buttons = QHBoxLayout()
        self.install_extensions_button = QPushButton(
            _("integration.inkscape.install_extensions"), self
        )
        self.install_extensions_button.setObjectName("installInkscapeExtensions")
        self.install_extensions_button.setEnabled(False)
        self.install_extensions_button.clicked.connect(self._install_inkscape_extensions)
        inksim_buttons.addWidget(self.install_extensions_button)
        self.remove_old_extensions_button = QPushButton(
            _("integration.inkscape.remove_old_extensions"), self
        )
        self.remove_old_extensions_button.setObjectName("removeOldInkscapeExtensions")
        self.remove_old_extensions_button.setEnabled(False)
        self.remove_old_extensions_button.clicked.connect(self._remove_old_inksim_extensions)
        inksim_buttons.addWidget(self.remove_old_extensions_button)
        inksim_layout.addLayout(inksim_buttons)
        layout.addWidget(inksim_group)

        report_group, report_layout = create_section(
            "integration.inkscape.section.report", "reportSection"
        )
        self.info_panel = QPlainTextEdit(self)
        self.info_panel.setObjectName("integrationReport")
        self.info_panel.setReadOnly(True)
        self.info_panel.setMinimumHeight(120)
        self.info_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.info_panel.setPlainText(_("integration.inkscape.report.waiting"))
        report_layout.addWidget(self.info_panel, 1)
        layout.addWidget(report_group, 1)

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
        self._user_extensions_directory = None
        self._inkscape_extension_roots = ()
        self._refresh_inksim_extensions()
        self.install_extensions_button.setEnabled(False)
        if not executable:
            self.executable_label.setText(_("integration.inkscape.not_found"))
            self.version_label.setText(
                _("integration.inkscape.version").format(
                    version=_("integration.inkscape.version_unavailable")
                )
            )
            unavailable = _("integration.inkscape.directory_unavailable")
            self.user_extensions_label.setText(
                _("integration.inkscape.user_extensions").format(path=unavailable)
            )
            self.system_extensions_label.setText(
                _("integration.inkscape.system_extensions").format(path=unavailable)
            )
            self._show_python_interpreter(None)
            self._set_report([_("integration.inkscape.report.not_found")])
            return

        executable_path = str(Path(executable).resolve())
        self.executable_label.setText(_sanitize_path_text(executable_path))
        self._start_probe(executable_path)

    def done(self, result: int) -> None:
        self._cancel_probe()
        super().done(result)

    def _start_probe(self, executable_path: str) -> None:
        self._probe_executable = executable_path
        self._probe_results = []
        self._probe_version = None
        self._probe_error = None
        self.version_label.setText(
            _("integration.inkscape.version").format(
                version=_("integration.inkscape.version_unavailable")
            )
        )
        self._set_report(
            [
                _("integration.inkscape.report.checking").format(
                    path=_sanitize_path_text(executable_path)
                )
            ]
        )
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
        step = len(self._probe_results)
        option = _PROBE_OPTIONS[step] if step < len(_PROBE_OPTIONS) else _VERSION_PROBE_OPTION
        process.start(self._probe_executable, [option])

    def _on_probe_step_done(self, process: QProcess, failed: bool = False) -> None:
        # Ignore late signals from a process that was already replaced, killed, or handled.
        if process is not self._probe_process:
            return
        self._probe_process = None
        self._probe_timer.stop()
        is_version_probe = len(self._probe_results) >= len(_PROBE_OPTIONS)
        output = ""
        step_error = None
        if failed:
            step_error = process.errorString()
        elif (
            not failed
            and process.exitStatus() == QProcess.ExitStatus.NormalExit
            and process.exitCode() == 0
        ):
            output = bytes(process.readAllStandardOutput().data()).decode(errors="replace").strip()
            if not output and not is_version_probe:
                step_error = "Inkscape returned no extension directory."
        elif process.exitStatus() == QProcess.ExitStatus.CrashExit:
            step_error = "Inkscape terminated unexpectedly."
        else:
            step_error = f"Inkscape exited with code {process.exitCode()}."
        process.deleteLater()
        if is_version_probe:
            self._probe_version = (
                output.splitlines()[0].strip() if not step_error and output else None
            )
            self._probe_results.append("")
            self._finish_probe(timed_out=False)
            return
        self._probe_error = step_error
        self._probe_results.append(output)
        if self._probe_error is not None:
            self._probe_results.extend([""] * (len(_PROBE_OPTIONS) - len(self._probe_results)))
            self._finish_probe(timed_out=False, error=self._probe_error)
        elif len(self._probe_results) < len(_PROBE_OPTIONS) + 1:
            self._run_next_probe()
        else:
            self._finish_probe(timed_out=False)

    def _on_probe_timeout(self) -> None:
        process = self._probe_process
        if process is None:
            return
        self._probe_process = None
        process.kill()
        process.deleteLater()
        if len(self._probe_results) >= len(_PROBE_OPTIONS):
            self._probe_version = None
            self._probe_results.append("")
            self._finish_probe(timed_out=False)
            return
        self._finish_probe(timed_out=True)

    def _finish_probe(self, timed_out: bool, error: str | None = None) -> None:
        self._set_probing(False)
        if timed_out or error is not None:
            # An unresponsive Inkscape will not answer the second query either, so do not wait twice.
            user_path = system_path = _("integration.inkscape.directory_unavailable")
        else:
            user_path, system_path = (
                self._extensions_directory(output)
                for output in self._probe_results[: len(_PROBE_OPTIONS)]
            )
        self._apply_extension_directories(user_path, system_path, timed_out, error)

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
        self, user_path: str, system_path: str, timed_out: bool, error: str | None = None
    ) -> None:
        report_entries = [
            _("integration.inkscape.report.executable").format(
                path=_sanitize_path_text(self._probe_executable)
            )
        ]
        version = self._probe_version or _("integration.inkscape.version_unavailable")
        self.version_label.setText(
            _("integration.inkscape.version").format(version=_sanitize_path_text(version))
        )
        if self._probe_version is not None:
            report_entries.append(
                _("integration.inkscape.report.version").format(
                    version=_sanitize_path_text(self._probe_version)
                )
            )
        if timed_out:
            report_entries.append(
                _("integration.inkscape.report.timeout").format(seconds=INKSCAPE_PROBE_TIMEOUT_S)
            )
            QMessageBox.warning(
                self,
                _("integration.inkscape.title"),
                _("integration.inkscape.timeout").format(seconds=INKSCAPE_PROBE_TIMEOUT_S),
            )
        elif error is not None:
            report_entries.append(
                _("integration.inkscape.report.probe_failed").format(
                    error=_sanitize_path_text(error)
                )
            )
            QMessageBox.warning(
                self,
                _("integration.inkscape.title"),
                _("integration.inkscape.probe_failed").format(error=_sanitize_path_text(error)),
            )
        self.user_extensions_label.setText(
            _("integration.inkscape.user_extensions").format(path=_sanitize_path_text(user_path))
        )
        self.system_extensions_label.setText(
            _("integration.inkscape.system_extensions").format(
                path=_sanitize_path_text(system_path)
            )
        )
        if (
            not timed_out
            and error is None
            and user_path != _("integration.inkscape.directory_unavailable")
        ):
            self._user_extensions_directory = Path(user_path)
            self.install_extensions_button.setEnabled(True)
        self._inkscape_extension_roots = tuple(
            (Path(path), user_install)
            for path, user_install in ((user_path, True), (system_path, False))
            if path != _("integration.inkscape.directory_unavailable")
        )
        if not timed_out and error is None:
            report_entries.extend(
                (
                    _("integration.inkscape.report.user_extensions").format(
                        path=_sanitize_path_text(user_path)
                    ),
                    _("integration.inkscape.report.system_extensions").format(
                        path=_sanitize_path_text(system_path)
                    ),
                )
            )
        extension_paths = [
            Path(path)
            for path in (user_path, system_path)
            if path != _("integration.inkscape.directory_unavailable")
        ]
        installations = (
            []
            if timed_out or error is not None
            else self._find_inkstitch_installations(extension_paths)
        )
        config = Config()
        previous_status = config.get(INKSCAPE_CONFIG_KEY)
        current_executable = os.path.normcase(str(Path(self._probe_executable).resolve()))
        stored_executable = (
            os.path.normcase(str(Path(previous_status["executable"]).expanduser().resolve()))
            if isinstance(previous_status, dict)
            and isinstance(previous_status.get("executable"), str)
            else None
        )
        previous_active = (
            previous_status.get("active_inkstitch")
            if isinstance(previous_status, dict) and stored_executable == current_executable
            else None
        )
        if isinstance(previous_active, str):
            previous_active = str(Path(previous_active).expanduser().resolve())
        self.inkstitch_combo.blockSignals(True)
        self.inkstitch_combo.clear()
        for installation in installations:
            self.inkstitch_combo.addItem(
                _sanitize_path_text(str(installation.resolved_path)), installation
            )
        self.inkstitch_combo.setVisible(len(installations) > 1)
        active_index = next(
            (
                index
                for index, installation in enumerate(installations)
                if str(installation.extension_dir) == previous_active
            ),
            0,
        )
        self.inkstitch_combo.setCurrentIndex(active_index if installations else -1)
        self.inkstitch_combo.blockSignals(False)
        if not installations:
            self.inkstitch_details_label.setText(_("integration.inkstitch.not_found"))
            report_entries.append(_("integration.inkscape.report.inkstitch_none"))
        else:
            self._show_inkstitch_command(active_index, persist=False)
            report_entries.append(
                _("integration.inkscape.report.inkstitch_found").format(count=len(installations))
            )

        preferences_file = None
        python_interpreter = None
        preferences_error = None
        interpreter_updated = False
        unavailable = _("integration.inkscape.directory_unavailable")
        if user_path != unavailable:
            preferences_file = (Path(user_path).parent / "preferences.xml").resolve()
            report_entries.append(
                _("integration.inkscape.report.preferences").format(
                    path=_sanitize_path_text(str(preferences_file))
                )
            )
            try:
                python_interpreter = self._read_python_interpreter(preferences_file)
            except (OSError, ET.ParseError) as ex:
                preferences_error = str(ex)
                report_entries.append(
                    _("integration.inkscape.report.preferences_error").format(
                        error=_sanitize_path_text(str(ex))
                    )
                )
                QMessageBox.warning(
                    self,
                    _("integration.inkscape.title"),
                    _("integration.inkscape.preferences_read_failed").format(
                        error=_sanitize_path_text(str(ex))
                    ),
                )
            if preferences_error is None:
                uvr_executable = self._find_uvr_executable(python_interpreter)
                if uvr_executable is None:
                    report_entries.append(
                        _("integration.inkscape.report.launcher_missing").format(
                            command="uvr-gui" if sys.platform == "win32" else "uvr"
                        )
                    )
                    QMessageBox.warning(
                        self,
                        _("integration.inkscape.title"),
                        _("integration.inkscape.uvr_missing").format(
                            command="uvr-gui" if sys.platform == "win32" else "uvr"
                        ),
                    )
                else:
                    target_interpreter = str(uvr_executable)
                    if python_interpreter != target_interpreter:
                        try:
                            self._write_python_interpreter(preferences_file, uvr_executable)
                            python_interpreter = self._read_python_interpreter(preferences_file)
                            if python_interpreter != target_interpreter:
                                raise ValueError(
                                    "Inkscape did not persist the requested Python interpreter."
                                )
                            interpreter_updated = True
                            report_entries.append(
                                _("integration.inkscape.report.interpreter_updated").format(
                                    path=_sanitize_path_text(python_interpreter)
                                )
                            )
                            report_entries.append(_("integration.inkscape.report.restart"))
                        except (OSError, ET.ParseError, expat.ExpatError, ValueError) as ex:
                            preferences_error = str(ex)
                            report_entries.append(
                                _("integration.inkscape.report.preferences_error").format(
                                    error=_sanitize_path_text(str(ex))
                                )
                            )
                            QMessageBox.warning(
                                self,
                                _("integration.inkscape.title"),
                                _("integration.inkscape.preferences_write_failed").format(
                                    error=_sanitize_path_text(str(ex))
                                ),
                            )
                    else:
                        report_entries.append(
                            _("integration.inkscape.report.interpreter_unchanged").format(
                                path=_sanitize_path_text(python_interpreter)
                            )
                        )
        else:
            report_entries.append(_("integration.inkscape.report.preferences_skipped"))
        self._show_python_interpreter(python_interpreter, interpreter_updated)

        installation_data = []
        for installation in installations:
            item = {
                "extension_dir": str(installation.extension_dir),
                "command": installation.command,
                "location": installation.location,
            }
            if installation.interpreter is not None:
                item["interpreter"] = installation.interpreter
            installation_data.append(item)
        result = {
            "executable": self._probe_executable,
            "status": (
                "error"
                if timed_out or error is not None
                else "found"
                if installations
                else "not_found"
            ),
            "user_extensions": user_path,
            "system_extensions": system_path,
            "inkstitch": installation_data,
        }
        if self._probe_version is not None:
            result["version"] = self._probe_version
        if preferences_file is not None:
            result["preferences_file"] = str(preferences_file)
        if python_interpreter is not None:
            result["python-interpretor"] = python_interpreter
        if preferences_error is not None:
            result["preferences_error"] = preferences_error
        if installations:
            result["active_inkstitch"] = str(installations[active_index].extension_dir)
        if error is not None:
            result["error"] = error
        try:
            config.set(INKSCAPE_CONFIG_KEY, result)
            report_entries.append(_("integration.inkscape.report.config_saved"))
        except (OSError, Timeout) as ex:
            report_entries.append(
                _("integration.inkscape.report.config_save_failed").format(
                    error=_sanitize_path_text(str(ex))
                )
            )
            QMessageBox.warning(
                self,
                _("integration.inkscape.title"),
                _("integration.inkscape.config_save_failed").format(
                    error=_sanitize_path_text(str(ex))
                ),
            )
        self._set_report(report_entries)
        self._refresh_inksim_extensions()

    def _refresh_inksim_extensions(self) -> None:
        try:
            installations = find_installed_inksim_extensions(self._inkscape_extension_roots)
        except (InstallSafetyError, OSError) as error:
            self._installed_inksim_extensions = ()
            self.inksim_extensions_list.setPlainText(
                _("integration.inkscape.inksim_scan_failed").format(
                    error=_sanitize_path_text(str(error))
                )
            )
            self.remove_old_extensions_button.setEnabled(False)
            self._append_report(
                _("integration.inkscape.report.inksim_scan_failed").format(
                    error=_sanitize_path_text(str(error))
                )
            )
            QMessageBox.warning(
                self,
                _("integration.inkscape.title"),
                _("integration.inkscape.inksim_scan_failed").format(
                    error=_sanitize_path_text(str(error))
                ),
            )
            return

        self._installed_inksim_extensions = installations
        current_target = (
            (self._user_extensions_directory / INSTALL_DIRECTORY).resolve()
            if self._user_extensions_directory is not None
            else None
        )
        lines = []
        if self._user_extensions_directory is not None:
            lines.append(
                _("integration.inkscape.inksim_user_current").format(
                    path=_sanitize_path_text(str(current_target)),
                    status=self._current_inksim_update_status(),
                )
            )
        for installation in installations:
            is_current_target = installation.user_install and installation.path == current_target
            if is_current_target:
                continue
            key = (
                "integration.inkscape.inksim_user_other"
                if installation.user_install
                else "integration.inkscape.inksim_system"
            )
            lines.append(_(key).format(path=_sanitize_path_text(str(installation.path))))
        self.inksim_extensions_list.setPlainText(
            "\n".join(lines) if lines else _("integration.inkscape.inksim_none")
        )

        has_old_user_installations = any(
            installation.user_install and installation.path != current_target
            for installation in installations
        )
        self.remove_old_extensions_button.setEnabled(has_old_user_installations)

    def _current_inksim_update_status(self) -> str:
        extension_root = self._user_extensions_directory
        if extension_root is None:
            return _("integration.inkscape.inksim_status_unavailable").format(
                error=_("integration.inkscape.directory_unavailable")
            )
        try:
            plan = prepare_install(extension_root, resolve_inksim_launcher())
        except (InstallSafetyError, OSError, ValueError) as error:
            return _("integration.inkscape.inksim_status_unavailable").format(
                error=_sanitize_path_text(str(error))
            )

        if not plan.destination.is_dir():
            return _("integration.inkscape.inksim_status_install")
        if not plan.update_required:
            return _("integration.inkscape.inksim_status_current")

        details = []
        if plan.update_files:
            details.append(
                _("integration.inkscape.inksim_status_changed_files").format(
                    files=", ".join(plan.update_files)
                )
            )
        if plan.command_changed:
            details.append(_("integration.inkscape.inksim_status_changed_command"))
        return _("integration.inkscape.inksim_status_update").format(details="; ".join(details))

    def _remove_old_inksim_extensions(self) -> None:
        user_extension_root = self._user_extensions_directory
        if user_extension_root is None:
            return
        current_target = (user_extension_root / INSTALL_DIRECTORY).resolve()
        old_installations = tuple(
            installation
            for installation in self._installed_inksim_extensions
            if installation.user_install and installation.path != current_target
        )
        if not old_installations:
            return

        directory_details = []
        try:
            for installation in old_installations:
                files = list_inksim_extension_files(installation.path)
                file_list = "\n".join(f"  - {name}" for name in files)
                directory_details.append(
                    f"{_sanitize_path_text(str(installation.path))}\n{file_list}"
                )
        except (InstallSafetyError, OSError) as error:
            self._show_remove_old_extensions_error(error)
            self._refresh_inksim_extensions()
            return

        answer = QMessageBox.question(
            self,
            _("integration.inkscape.remove_old_extensions"),
            _("integration.inkscape.remove_old_extensions_confirm").format(
                directories="\n\n".join(directory_details)
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        try:
            for installation in old_installations:
                remove_old_inksim_extension(
                    installation.path,
                    user_extension_root,
                    confirmed=True,
                )
        except (InstallSafetyError, OSError) as error:
            self._show_remove_old_extensions_error(error)
            self._refresh_inksim_extensions()
            return

        message = _("integration.inkscape.remove_old_extensions_success")
        self._append_report(message)
        self._refresh_inksim_extensions()
        QMessageBox.information(self, _("integration.inkscape.title"), message)

    def _show_remove_old_extensions_error(self, error: Exception) -> None:
        message = _("integration.inkscape.remove_old_extensions_failed").format(
            error=_sanitize_path_text(str(error))
        )
        self._append_report(message)
        QMessageBox.critical(self, _("integration.inkscape.title"), message)

    def _install_inkscape_extensions(self) -> None:
        extension_directory = self._user_extensions_directory
        if extension_directory is None:
            return

        try:
            launcher = resolve_inksim_launcher()
            plan = prepare_install(extension_directory, launcher)
        except (InstallSafetyError, OSError, ValueError) as error:
            self._show_extension_install_error(error)
            return

        if plan.requires_confirmation and not self._confirm_extension_install(plan):
            return

        try:
            destination = install_extension(plan, confirmed=True)
        except (InstallSafetyError, OSError, ValueError) as error:
            self._show_extension_install_error(error)
            return

        message = _("integration.inkscape.install_extensions_success").format(
            path=_sanitize_path_text(str(destination))
        )
        self._append_report(message)
        self._refresh_inksim_extensions()
        QMessageBox.information(self, _("integration.inkscape.title"), message)

    def _confirm_extension_install(self, plan: InstallPlan) -> bool:
        replace_files = "\n".join(plan.replace_files) or _("integration.inkscape.install_none")
        preserve_files = "\n".join(plan.preserved_files) or _("integration.inkscape.install_none")
        message = _("integration.inkscape.install_extensions_confirm").format(
            replace_files=replace_files,
            preserve_files=preserve_files,
        )
        answer = QMessageBox.question(
            self,
            _("integration.inkscape.install_extensions"),
            message,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return answer == QMessageBox.Yes

    def _show_extension_install_error(self, error: Exception) -> None:
        message = _("integration.inkscape.install_extensions_failed").format(
            error=_sanitize_path_text(str(error))
        )
        self._append_report(message)
        QMessageBox.critical(self, _("integration.inkscape.title"), message)

    def _set_report(self, entries: list[str]) -> None:
        self._report_entries = entries
        self.info_panel.setPlainText("\n".join(entries))

    def _append_report(self, entry: str) -> None:
        self._report_entries.append(entry)
        self.info_panel.setPlainText("\n".join(self._report_entries))

    def _show_inkstitch_command(self, index: int, persist: bool = True) -> None:
        installation = self.inkstitch_combo.itemData(index)
        if not isinstance(installation, InkStitchInstallation):
            return
        self.inkstitch_details_label.setText(
            "\n".join(
                (
                    _("integration.inkstitch.location").format(value=installation.location),
                    _("integration.inkstitch.interpreter").format(
                        value=_sanitize_path_text(installation.interpreter or "")
                    ),
                    _("integration.inkstitch.command").format(
                        value=_sanitize_path_text(installation.command)
                    ),
                    _("integration.inkstitch.resolved_path").format(
                        path=_sanitize_path_text(str(installation.resolved_path))
                    ),
                )
            )
        )
        if persist:
            extension_dir = str(installation.extension_dir)

            def set_active_installation(status: Any) -> dict[str, Any]:
                stored_executable = (
                    str(Path(status["executable"]).expanduser().resolve())
                    if isinstance(status, dict) and isinstance(status.get("executable"), str)
                    else None
                )
                if not isinstance(status, dict) or os.path.normcase(
                    stored_executable or ""
                ) != os.path.normcase(str(Path(self._probe_executable).resolve())):
                    raise ValueError("The cached Inkscape installation status has changed.")
                return {**status, "active_inkstitch": extension_dir}

            try:
                Config().update(INKSCAPE_CONFIG_KEY, set_active_installation)
                self._append_report(
                    _("integration.inkscape.report.active_inkstitch_updated").format(
                        path=_sanitize_path_text(extension_dir)
                    )
                )
            except (OSError, Timeout, ValueError) as ex:
                self._append_report(
                    _("integration.inkscape.report.config_save_failed").format(
                        error=_sanitize_path_text(str(ex))
                    )
                )
                QMessageBox.warning(
                    self,
                    _("integration.inkscape.title"),
                    _("integration.inkscape.config_save_failed").format(
                        error=_sanitize_path_text(str(ex))
                    ),
                )

    @staticmethod
    def _read_python_interpreter(preferences_file: Path) -> str | None:
        try:
            root = ET.parse(preferences_file).getroot()
        except FileNotFoundError:
            return None

        for group in root.iter():
            if (
                not isinstance(group.tag, str)
                or group.tag.rsplit("}", 1)[-1] != "group"
                or group.get("id") != "extensions"
            ):
                continue
            value = (group.get("python-interpreter") or "").strip()
            if value:
                return value
            for parameter in group.iter():
                if (
                    parameter.tag.rsplit("}", 1)[-1] == "param"
                    and parameter.get("name") == "python-interpreter"
                ):
                    value = (parameter.text or "").strip() or (parameter.get("value") or "").strip()
                    return value or None
        return None

    @staticmethod
    def _find_uvr_executable(current_interpreter: str | None) -> Path | None:
        command = "uvr-gui" if sys.platform == "win32" else "uvr"
        executable = shutil.which(command)
        if executable is None:
            local_bin = Path.home() / ".local" / "bin"
            candidate_names = (command, f"{command}.exe", f"{command}.cmd")
            executable = next(
                (
                    str(candidate)
                    for name in candidate_names
                    if (candidate := local_bin / name).is_file()
                ),
                None,
            )
        if executable is None and current_interpreter is not None:
            configured_path = Path(current_interpreter).expanduser()
            configured_names = {command, f"{command}.exe", f"{command}.cmd"}
            if configured_path.name.lower() in configured_names and configured_path.is_file():
                executable = str(configured_path)
        if executable is None:
            return None

        executable_path = Path(executable).expanduser().absolute()
        if not executable_path.is_file() or not os.access(executable_path, os.X_OK):
            return None
        return executable_path

    @staticmethod
    def _write_python_interpreter(preferences_file: Path, interpreter: Path) -> None:
        original = preferences_file.read_bytes()
        group_start = None
        document_encoding = None
        parser = expat.ParserCreate(namespace_separator="}")

        def find_extensions_group(name: str, attributes: dict[str, str]) -> None:
            nonlocal group_start
            if (
                group_start is None
                and name.rsplit("}", 1)[-1] == "group"
                and attributes.get("id") == "extensions"
            ):
                group_start = parser.CurrentByteIndex

        def record_encoding(version: str, encoding: str | None, standalone: int) -> None:
            nonlocal document_encoding
            document_encoding = encoding

        parser.StartElementHandler = find_extensions_group
        parser.XmlDeclHandler = record_encoding
        parser.Parse(original, True)
        if document_encoding and document_encoding.lower().replace("_", "-") not in {
            "utf-8",
            "utf8",
        }:
            raise ValueError(
                f"Cannot preserve the {document_encoding} encoding of {preferences_file}."
            )
        if group_start is None:
            raise ValueError(f"Could not find the Inkscape extensions group in {preferences_file}.")

        quote: int | None = None
        tag_end = None
        for offset in range(group_start, len(original)):
            character = original[offset]
            if quote is not None:
                if character == quote:
                    quote = None
            elif character in (ord('"'), ord("'")):
                quote = character
            elif character == ord(">"):
                tag_end = offset
                break
        if tag_end is None:
            raise ValueError(
                f"Could not find the end of the extensions group in {preferences_file}."
            )

        start_tag = original[group_start : tag_end + 1]
        attribute_pattern = re.compile(
            rb"(?P<space>[ \t\r\n]+)(?P<name>[^ \t\r\n=/>]+)"
            rb"[ \t\r\n]*=[ \t\r\n]*(?P<quote>[\"'])(?P<value>.*?)(?P=quote)",
            re.DOTALL,
        )
        attributes = list(attribute_pattern.finditer(start_tag))
        interpreter_attribute = next(
            (
                attribute
                for attribute in attributes
                if attribute.group("name") == b"python-interpreter"
            ),
            None,
        )
        interpreter_value = str(interpreter)
        if interpreter_attribute is not None:
            quote_byte = interpreter_attribute.group("quote")
            replacements = {'"': "&quot;"} if quote_byte == b'"' else {"'": "&apos;"}
            escaped_value = escape_xml_attribute(interpreter_value, replacements).encode("utf-8")
            updated_tag = (
                start_tag[: interpreter_attribute.start("value")]
                + escaped_value
                + start_tag[interpreter_attribute.end("value") :]
            )
        else:
            last_attribute = attributes[-1]
            name_start = last_attribute.start("name")
            line_start = start_tag.rfind(b"\n", 0, name_start) + 1
            indentation = start_tag[line_start:name_start]
            if b"\n" in start_tag[:name_start] and not indentation.strip(b" \t"):
                newline = b"\r\n" if b"\r\n" in start_tag else b"\n"
                separator = newline + indentation
            else:
                separator = b" "
            addition = (
                separator
                + b'python-interpreter="'
                + escape_xml_attribute(interpreter_value, {'"': "&quot;"}).encode("utf-8")
                + b'"'
            )
            insert_at = last_attribute.end()
            updated_tag = start_tag[:insert_at] + addition + start_tag[insert_at:]

        updated = original[:group_start] + updated_tag + original[tag_end + 1 :]
        verification_parser = expat.ParserCreate(namespace_separator="}")
        verification_parser.Parse(updated, True)

        original_mode = preferences_file.stat().st_mode & 0o777
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=preferences_file.name + ".",
            suffix=".tmp",
            dir=preferences_file.parent,
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as temporary_file:
                temporary_file.write(updated)
            os.chmod(temporary_path, original_mode)
            os.replace(temporary_path, preferences_file)
        finally:
            with suppress(OSError):
                temporary_path.unlink(missing_ok=True)

    def _show_python_interpreter(
        self, interpreter: str | None, restart_required: bool = False
    ) -> None:
        value = interpreter or _("integration.inkscape.python_interpreter_unset")
        label = _("integration.inkscape.python_interpreter").format(path=_sanitize_path_text(value))
        if restart_required:
            label += "\n" + _("integration.inkscape.python_interpreter_restart")
        self.python_interpreter_label.setText(label)

    @staticmethod
    def _find_inkstitch_installations(
        extension_paths: list[Path],
    ) -> list[InkStitchInstallation]:
        installations: dict[Path, InkStitchInstallation] = {}
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
                        installations[resolved_inx_path] = InkStitchInstallation(
                            inx_path=resolved_inx_path,
                            command=command,
                            interpreter=element.get("interpreter"),
                            location=element.get("location", ""),
                        )
                        break
        return sorted(
            installations.values(),
            key=lambda item: str(item.resolved_path).casefold(),
        )
