# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ..i18n import _


class CalibrationDialog(QDialog):
    """Measure the real on-screen size to calibrate 1:1 zoom.

    The user drags the slider until the on-screen bar matches a physical
    ruler (e.g. 100 mm), then confirms. The resulting pixels-per-mm is
    returned so the caller can persist it per display.
    """

    def __init__(
        self,
        parent: QWidget | None,
        initial_px_per_mm: float | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("dialog.calibrate.title"))
        self.resize(720, 260)
        self._px_per_mm: float | None = None

        root = QVBoxLayout(self)

        info = QLabel(_("dialog.calibrate.info"))
        info.setWordWrap(True)
        root.addWidget(info)

        self._bar = _RulerBar(self)
        self._bar.setFixedHeight(60)
        root.addWidget(self._bar)

        slider_row = QHBoxLayout()
        slider_row.addWidget(QLabel(_("dialog.calibrate.bar_length")))
        self._slider = QSlider(Qt.Horizontal)
        self._slider.setRange(100, 2000)
        self._slider.valueChanged.connect(self._bar.set_pixel_length)
        self._slider.valueChanged.connect(self._update_length_label)
        slider_row.addWidget(self._slider, 1)
        self._length_label = QLabel()
        slider_row.addWidget(self._length_label)
        root.addLayout(slider_row)

        mm_row = QHBoxLayout()
        mm_row.addWidget(QLabel(_("dialog.calibrate.physical_length")))
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

    def _update_length_label(self) -> None:
        self._length_label.setText(f"{self._slider.value()} px")

    def _accept(self) -> None:
        pixel_length = self._slider.value()
        physical_mm = self._mm_spin.value()
        if physical_mm <= 0:
            return
        self._px_per_mm = pixel_length / physical_mm
        self.accept()

    def pixels_per_mm(self) -> float | None:
        return self._px_per_mm


class _RulerBar(QWidget):
    """A horizontal bar with tick marks used for physical calibration."""

    def __init__(self, parent: QWidget | None) -> None:
        super().__init__(parent)
        self._pixel_length = 500

    def set_pixel_length(self, length: int) -> None:
        self._pixel_length = length
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
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
