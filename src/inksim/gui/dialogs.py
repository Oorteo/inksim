# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

import time
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFileDialog, QHBoxLayout, QLabel,
                               QListWidget, QPushButton, QSlider, QSplitter,
                               QVBoxLayout, QWidget)

from ..formats import get_supported_input_extensions
from .viewer import EmbroideryViewerWidget, density_debug


class CalibrationDialog(QDialog):
    """Measure the real on-screen size to calibrate 1:1 zoom.

    The user drags the slider until the on-screen bar matches a physical
    ruler (e.g. 100 mm), then confirms. The resulting pixels-per-mm is
    returned so the caller can persist it per display.
    """

    def __init__(self, parent, initial_px_per_mm=None):
        super().__init__(parent)
        self.setWindowTitle("Calibrate display size")
        self.resize(720, 260)
        self._px_per_mm = None

        root = QVBoxLayout(self)

        info = QLabel(
            "Hold a ruler against the screen and drag the slider until the "
            "bar below is exactly 100 mm long, then press OK."
        )
        info.setWordWrap(True)
        root.addWidget(info)

        self._bar = _RulerBar(self)
        self._bar.setFixedHeight(60)
        root.addWidget(self._bar)

        slider_row = QHBoxLayout()
        slider_row.addWidget(QLabel("Bar length:"))
        self._slider = QSlider(Qt.Horizontal)
        self._slider.setRange(100, 2000)
        self._slider.valueChanged.connect(self._bar.set_pixel_length)
        self._slider.valueChanged.connect(self._update_length_label)
        slider_row.addWidget(self._slider, 1)
        self._length_label = QLabel()
        slider_row.addWidget(self._length_label)
        root.addLayout(slider_row)

        mm_row = QHBoxLayout()
        mm_row.addWidget(QLabel("Physical length of the bar (mm):"))
        self._mm_spin = QDoubleSpinBox()
        self._mm_spin.setRange(1.0, 1000.0)
        self._mm_spin.setDecimals(1)
        self._mm_spin.setValue(100.0)
        mm_row.addWidget(self._mm_spin)
        mm_row.addStretch()
        root.addLayout(mm_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        # Pre-load the stored calibration (if any) so the bar starts at the
        # previously measured length instead of a fixed default.
        if initial_px_per_mm and initial_px_per_mm > 0:
            initial_px = int(round(initial_px_per_mm * self._mm_spin.value()))
            initial_px = max(self._slider.minimum(), min(self._slider.maximum(), initial_px))
            self._slider.setValue(initial_px)
        self._bar.set_pixel_length(self._slider.value())
        self._update_length_label()

    def _update_length_label(self):
        self._length_label.setText(f"{self._slider.value()} px")

    def _accept(self):
        pixel_length = self._slider.value()
        physical_mm = self._mm_spin.value()
        if physical_mm <= 0:
            return
        self._px_per_mm = pixel_length / physical_mm
        self.accept()

    def pixels_per_mm(self):
        return self._px_per_mm


class _RulerBar(QWidget):
    """A horizontal bar with tick marks used for physical calibration."""

    def __init__(self, parent):
        super().__init__(parent)
        self._pixel_length = 500

    def set_pixel_length(self, length):
        self._pixel_length = length
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor(250, 250, 250))
        x0 = 20
        y = self.height() // 2
        painter.setPen(QPen(QColor(30, 30, 30), 2))
        painter.drawLine(x0, y, x0 + self._pixel_length, y)
        # End caps and center tick.
        painter.drawLine(x0, y - 12, x0, y + 12)
        painter.drawLine(x0 + self._pixel_length, y - 12, x0 + self._pixel_length, y + 12)
        painter.setPen(QPen(QColor(120, 120, 120), 1))
        painter.drawLine(x0 + self._pixel_length // 2, y - 8, x0 + self._pixel_length // 2, y + 8)
        painter.end()


class EmbroideryOpenDialog(QDialog):
    """Browse embroidery files with an in-app design preview."""

    def __init__(self, parent, initial_directory, selected_file=None, recent_directories=None):
        super().__init__(parent)
        self.setWindowTitle("Open embroidery file")
        self.resize(1100, 720)
        self.selected_path: Path | None = None
        self.current_directory = Path(initial_directory or Path.cwd()).resolve()
        self.initial_file = Path(selected_file).resolve() if selected_file else None
        self.extensions = get_supported_input_extensions()
        root_layout = QVBoxLayout(self)
        directory_layout = QHBoxLayout()
        self.directory_text = QComboBox(self)
        self.directory_text.setEditable(True)
        directory_layout.addWidget(self.directory_text, 1)
        up_button = QPushButton("Up", self)
        browse_button = QPushButton("Browse...", self)
        directory_layout.addWidget(up_button)
        directory_layout.addWidget(browse_button)
        root_layout.addLayout(directory_layout)
        recent_layout = QHBoxLayout()
        recent_layout.addWidget(QLabel("Recent:", self))
        self.recent_combo = QComboBox(self)
        self.recent_combo.addItem("— choose directory —")
        for directory in (recent_directories or []):
            self.recent_combo.addItem(directory)
        self.recent_combo.setEnabled(self.recent_combo.count() > 1)
        recent_layout.addWidget(self.recent_combo, 1)
        root_layout.addLayout(recent_layout)
        self.file_list = QListWidget(self)
        preview_container = QWidget(self)
        preview_container.setLayout(QVBoxLayout())
        self.preview = EmbroideryViewerWidget(preview_container, None)
        self.preview.show_grid = False
        self.preview.show_needle = False
        preview_container.layout().addWidget(self.preview)
        splitter = QSplitter(Qt.Horizontal, self)
        splitter.addWidget(self.file_list)
        splitter.addWidget(preview_container)
        splitter.setStretchFactor(1, 1)
        root_layout.addWidget(splitter, 1)
        button_layout = QHBoxLayout()
        self._real_preview_button = QPushButton("Real preview", self)
        self._real_preview_button.setCheckable(True)
        self._real_preview_button.setChecked(self.preview.active_renderer == "gpu_textured")
        self._real_preview_button.clicked.connect(self._toggle_real_preview)
        self.preview.renderer_changed.connect(self._sync_real_preview_button)
        button_layout.addWidget(self._real_preview_button)
        button_layout.addStretch()
        ok_button = QPushButton("OK", self)
        ok_button.setDefault(True)
        ok_button.clicked.connect(self.open_selected)
        cancel_button = QPushButton("Cancel", self)
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(cancel_button)
        button_layout.addWidget(ok_button)
        root_layout.addLayout(button_layout)
        self.file_list.currentRowChanged.connect(self._on_row_changed)
        self.file_list.itemDoubleClicked.connect(self.open_selected)
        self.directory_text.lineEdit().returnPressed.connect(self.change_directory)
        self.recent_combo.currentIndexChanged.connect(self._on_recent_selected)
        up_button.clicked.connect(self.go_to_parent_directory)
        browse_button.clicked.connect(self.browse_directory)
        self.refresh_files()
        QTimer.singleShot(0, self.file_list.setFocus)

    def _on_recent_selected(self, index):
        if index <= 0:
            return
        directory = self.recent_combo.itemText(index)
        self.recent_combo.setCurrentIndex(0)
        self.set_directory(directory)

    def _toggle_real_preview(self):
        self.preview.toggle_display_mode("Z")

    def _sync_real_preview_button(self, renderer_key):
        is_real = renderer_key == "gpu_textured"
        self._real_preview_button.setChecked(is_real)
        self._real_preview_button.setText(
            "Normal preview" if is_real else "Real preview"
        )

    def refresh_files(self):
        if not self.current_directory.is_dir():
            return
        directories = sorted((path for path in self.current_directory.iterdir()
                              if path.is_dir()), key=lambda path: path.name.lower())
        self.directory_text.blockSignals(True)
        self.directory_text.clear()
        self.directory_text.addItems([str(self.current_directory),
                                      *(str(path) for path in directories)])
        self.directory_text.setCurrentText(str(self.current_directory))
        self.directory_text.blockSignals(False)
        files = sorted((path for path in self.current_directory.iterdir()
                        if path.is_file() and path.suffix.lower().lstrip(".")
                        in self.extensions), key=lambda path: path.name.lower())
        self.file_paths = files
        self.file_list.clear()
        self.file_list.addItems([path.name for path in files])
        self._resize_file_list(files)
        self.selected_path = None
        if files:
            selected_index = next((index for index, path in enumerate(files)
                                   if path == self.initial_file), 0)
            self.file_list.setCurrentRow(selected_index)

    def _resize_file_list(self, files):
        widest = max((self.file_list.fontMetrics().horizontalAdvance(path.name)
                      for path in files), default=0)
        self.file_list.setMinimumWidth(min(max(160, widest + 32),
                                           max(160, self.width() - 432)))

    def _on_row_changed(self, row):
        if row < 0 or row >= len(self.file_paths):
            return
        self.selected_path = self.file_paths[row]
        density_debug(f"dialog row changed row={row} path={self.selected_path!s}")
        started_at = time.perf_counter()
        self.preview.load_design(
            str(self.selected_path),
            fit_to_screen=True,
            precompute_density=False,
        )
        density_debug(
            f"dialog preview load returned row={row} "
            f"elapsed={time.perf_counter() - started_at:.3f}s"
        )

    def open_selected(self):
        if self.selected_path:
            self.accept()

    def cancel_dialog(self):
        self.reject()

    @property
    def background_color(self):
        """Return the preview viewer's background colour chosen by the user."""
        return self.preview.background_color

    def change_directory(self):
        self.set_directory(self.directory_text.currentText())

    def set_directory(self, directory):
        path = Path(directory).expanduser().resolve()
        if path.is_dir() and path != self.current_directory:
            self.current_directory = path
            self.initial_file = None
            self.refresh_files()

    def go_to_parent_directory(self):
        self.set_directory(self.current_directory.parent)

    def browse_directory(self):
        directory = QFileDialog.getExistingDirectory(self, "Choose directory",
                                                      str(self.current_directory))
        if directory:
            self.set_directory(directory)
