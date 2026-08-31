from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
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
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(640, 480)
        self.resize(1100, 760)
        self._image = image
        self._default_name = default_name
        self._file_filter = file_filter
        self._extension = extension
        self._render_callback = render_callback
        self._transparent_changed_callback = on_transparent_changed
        self._selected_path = None

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(12, 12, 12, 12)

        self._info_label = QLabel(f"{image.width()} x {image.height()} pixels")
        self._info_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._info_label)

        self._preview = _PreviewWidget(image)
        layout.addWidget(self._preview, 1)

        options_layout = QHBoxLayout()
        options_layout.addStretch()
        self._transparent_check = QCheckBox("Transparent background")
        self._transparent_check.setChecked(transparent_default)
        self._transparent_check.toggled.connect(self._on_transparent_changed)
        if render_callback is None:
            self._transparent_check.setEnabled(False)
        options_layout.addWidget(self._transparent_check)
        options_layout.addStretch()
        layout.addLayout(options_layout)

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

    def _on_transparent_changed(self, checked):
        if self._transparent_changed_callback is not None:
            self._transparent_changed_callback(checked)
        if self._render_callback is None:
            return
        new_image = self._render_callback(transparent=checked)
        if new_image is not None:
            self._image = new_image
            self._preview.set_image(self._image)
            self._info_label.setText(f"{self._image.width()} x {self._image.height()} pixels")

    def _copy_to_clipboard(self):
        clipboard = QApplication.clipboard()
        clipboard.setPixmap(QPixmap.fromImage(self._image))
        self._copy_button.setText("Copied!")
        self._copy_button.setEnabled(False)

    def _save_image(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save image",
            self._default_name,
            self._file_filter,
        )
        if not path:
            return
        selected_path = Path(path)
        selected_path = selected_path.with_suffix(self._extension)
        if not self._image.save(str(selected_path), "PNG"):
            QMessageBox.critical(self, "Save image", f"Failed to save {selected_path}")
            return
        self._selected_path = selected_path
        self._save_button.setText("Saved!")
        self._save_button.setEnabled(False)

    def selected_path(self):
        return self._selected_path
