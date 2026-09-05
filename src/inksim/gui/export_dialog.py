# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class _PreviewWidget(QWidget):
    """Widget that paints the preview image scaled to its current size."""

    def __init__(self, image, parent=None):
        super().__init__(parent)
        self._image = image
        self.setMinimumSize(40, 40)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_image(self, image):
        self._image = image
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        rect = self.rect()
        pixmap = QPixmap.fromImage(self._image)
        scaled = pixmap.scaled(
            rect.width(),
            rect.height(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        x = (rect.width() - scaled.width()) // 2
        y = (rect.height() - scaled.height()) // 2
        painter.drawPixmap(x, y, scaled)
        painter.end()


class ExportPreviewDialog(QDialog):
    """Modal dialog showing an exported image with copy-to-clipboard or save options."""

    MAX_SIDE_PX = 8192
    SCALE_FACTORS = [1, 2, 4, 8]
    FORMATS = ["PNG", "WebP"]
    QUALITIES = [100, 95, 90, 80]

    def __init__(
        self,
        title,
        image,
        default_name,
        file_filter,
        extension,
        render_callback=None,
        transparent_default=False,
        on_transparent_changed=None,
        parent=None,
        base_dpi=300,
        design_width_mm=0.0,
        design_height_mm=0.0,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(640, 480)
        self.resize(1100, 760)
        self._image = image
        self._base_width = image.width()
        self._base_height = image.height()
        self._base_dpi = base_dpi
        self._design_width_mm = design_width_mm
        self._design_height_mm = design_height_mm
        self._default_name = default_name
        self._file_filter = file_filter
        self._extension = extension
        self._render_callback = render_callback
        self._transparent_changed_callback = on_transparent_changed
        self._selected_path = None

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(12, 12, 12, 12)

        self._info_label = QLabel(self._format_info(1.0))
        self._info_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._info_label)

        self._preview = _PreviewWidget(image)
        layout.addWidget(self._preview, 1)

        options_layout = QHBoxLayout()
        options_layout.addStretch()

        self._scale_combo = QComboBox()
        for scale in self.SCALE_FACTORS:
            self._scale_combo.addItem(f"{scale}x", scale)
        self._scale_combo.setCurrentIndex(0)
        self._scale_combo.currentIndexChanged.connect(self._on_scale_changed)
        options_layout.addWidget(QLabel("Scale:"))
        options_layout.addWidget(self._scale_combo)

        self._format_combo = QComboBox()
        for fmt in self.FORMATS:
            self._format_combo.addItem(fmt, fmt)
        self._format_combo.currentIndexChanged.connect(self._on_format_changed)
        options_layout.addWidget(QLabel("Format:"))
        options_layout.addWidget(self._format_combo)

        self._quality_combo = QComboBox()
        for quality in self.QUALITIES:
            self._quality_combo.addItem(f"{quality}%", quality)
        self._quality_combo.setCurrentIndex(1)  # default 95%
        self._quality_combo.currentIndexChanged.connect(self._on_quality_changed)
        options_layout.addWidget(QLabel("Quality:"))
        options_layout.addWidget(self._quality_combo)
        options_layout.addSpacing(16)

        self._transparent_check = QCheckBox("Transparent background")
        self._transparent_check.setChecked(transparent_default)
        self._transparent_check.toggled.connect(self._on_transparent_changed)
        if render_callback is None:
            self._transparent_check.setEnabled(False)
        options_layout.addWidget(self._transparent_check)
        options_layout.addStretch()
        layout.addLayout(options_layout)

        self._update_scale_availability()
        self._update_quality_visibility()

        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self._copy_button = QPushButton("Copy to clipboard")
        self._copy_button.setToolTip("Copy the full-resolution image to the clipboard")
        self._copy_button.clicked.connect(self._copy_to_clipboard)
        button_layout.addWidget(self._copy_button)

        self._save_button = QPushButton("Save...")
        self._save_button.setToolTip("Save the image to a file")
        self._save_button.clicked.connect(self._save_image)
        button_layout.addWidget(self._save_button)

        self._close_button = QPushButton("Close")
        self._close_button.setDefault(True)
        self._close_button.clicked.connect(self.reject)
        button_layout.addWidget(self._close_button)

        button_layout.addStretch()
        layout.addLayout(button_layout)

    def _format_info(self, scale):
        width = max(1, round(self._base_width * scale))
        height = max(1, round(self._base_height * scale))
        effective_dpi = round(self._base_dpi * scale)
        return (
            f"{width} x {height} px | "
            f"{effective_dpi} DPI | "
            f"{self._design_width_mm:.1f} x {self._design_height_mm:.1f} mm"
        )

    def _max_allowed_scale(self):
        if self._base_width <= 0 or self._base_height <= 0:
            return 1
        return min(
            self.MAX_SIDE_PX / self._base_width,
            self.MAX_SIDE_PX / self._base_height,
        )

    def _update_scale_availability(self):
        max_scale = self._max_allowed_scale()
        model = self._scale_combo.model()
        for index, scale in enumerate(self.SCALE_FACTORS):
            item = model.item(index, 0)
            if item is None:
                continue
            if scale <= max_scale:
                item.setFlags(item.flags() | Qt.ItemIsEnabled)
            else:
                item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
        current = self._current_scale()
        if current > max_scale:
            for scale in reversed(self.SCALE_FACTORS):
                if scale <= max_scale:
                    self._scale_combo.setCurrentIndex(self.SCALE_FACTORS.index(scale))
                    break

    def _update_quality_visibility(self):
        fmt = self._current_format()
        self._quality_combo.setEnabled(fmt == "WebP")
        self._quality_combo.setVisible(fmt == "WebP")

    def _current_scale(self):
        return self._scale_combo.currentData()

    def _current_format(self):
        return self._format_combo.currentData()

    def _current_quality(self):
        return self._quality_combo.currentData()

    def _is_transparent_allowed(self):
        return self._current_format() in ("PNG", "WebP")

    def _on_scale_changed(self):
        self._update_scale_availability()
        self._regenerate_preview()

    def _on_format_changed(self):
        self._update_quality_visibility()
        if not self._is_transparent_allowed() and self._transparent_check.isChecked():
            self._transparent_check.setChecked(False)
        self._transparent_check.setEnabled(self._is_transparent_allowed() and self._render_callback is not None)
        self._regenerate_preview()

    def _on_quality_changed(self):
        if self._current_format() == "WebP":
            self._regenerate_preview()

    def _reset_action_buttons(self):
        """Re-enable Copy/Save after the preview changes."""
        if self._copy_button.text() != "Copy to clipboard":
            self._copy_button.setText("Copy to clipboard")
            self._copy_button.setEnabled(True)
        if self._save_button.text() != "Save...":
            self._save_button.setText("Save...")
            self._save_button.setEnabled(True)

    def _regenerate_preview(self):
        self._reset_action_buttons()
        if self._render_callback is None:
            self._info_label.setText(self._format_info(self._current_scale()))
            return
        transparent = self._is_transparent_allowed() and self._transparent_check.isChecked()
        new_image = self._render_callback(
            transparent=transparent,
            scale_factor=self._current_scale(),
            format=self._current_format(),
            quality=self._current_quality(),
        )
        if new_image is not None:
            self._image = new_image
            self._preview.set_image(self._image)
            self._info_label.setText(self._format_info(self._current_scale()))

    def _on_transparent_changed(self, checked):
        if self._transparent_changed_callback is not None:
            self._transparent_changed_callback(checked)
        if not self._is_transparent_allowed():
            return
        self._regenerate_preview()

    def _format_suffix(self):
        return {
            "PNG": ".png",
            "WebP": ".webp",
        }[self._current_format()]

    def _copy_to_clipboard(self):
        clipboard = QApplication.clipboard()
        clipboard.setPixmap(QPixmap.fromImage(self._image))
        self._copy_button.setText("Copied!")
        self._copy_button.setEnabled(False)

    def _save_image(self):
        default_name = str(Path(self._default_name).with_suffix(self._format_suffix()))
        file_filter = {
            "PNG": "PNG files (*.png)",
            "WebP": "WebP files (*.webp)",
        }[self._current_format()]
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save image",
            default_name,
            file_filter,
        )
        if not path:
            return
        selected_path = Path(path)
        selected_path = selected_path.with_suffix(self._format_suffix())
        fmt = self._current_format()
        quality = self._current_quality() if fmt == "WebP" else -1
        if not self._image.save(str(selected_path), fmt, quality):
            QMessageBox.critical(self, "Save image", f"Failed to save {selected_path}")
            return
        self._selected_path = selected_path
        self._save_button.setText("Saved!")
        self._save_button.setEnabled(False)

    def selected_path(self):
        return self._selected_path
