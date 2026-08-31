from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
)


class ExportPreviewDialog(QDialog):
    """Modal dialog showing an exported image with copy-to-clipboard or save options."""

    def __init__(self, title, image, default_name, file_filter, extension, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(420, 340)
        self.resize(720, 520)
        self._image = image
        self._default_name = default_name
        self._file_filter = file_filter
        self._extension = extension
        self._selected_path = None

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(12, 12, 12, 12)

        info = QLabel(f"{image.width()} x {image.height()} pixels")
        info.setAlignment(Qt.AlignCenter)
        layout.addWidget(info)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setAlignment(Qt.AlignCenter)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._label = QLabel()
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._update_pixmap()
        scroll.setWidget(self._label)
        layout.addWidget(scroll, 1)

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

    def _update_pixmap(self):
        pixmap = QPixmap.fromImage(self._image)
        # Scale to fit the dialog while keeping aspect ratio; keep the source
        # image at full resolution for clipboard / save operations.
        available = self._label.size()
        if available.width() > 0 and available.height() > 0:
            scaled = pixmap.scaled(
                available.width(),
                available.height(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
        else:
            scaled = pixmap
        self._label.setPixmap(scaled)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_pixmap()

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
