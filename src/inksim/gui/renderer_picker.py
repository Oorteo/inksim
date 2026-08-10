"""Renderer selection dialog with a live representative preview."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
)

from ..render import STITCH_RENDERERS, preview_stitches


class RendererPickerDialog(QDialog):
    """Choose a stitch renderer and preview its output."""

    def __init__(self, parent, selected_renderer):
        super().__init__(parent)
        self.setWindowTitle("Choose stitch renderer")
        self.resize(440, 360)
        self.selected_renderer = selected_renderer
        layout = QVBoxLayout(self)

        self.renderer_combo = QComboBox(self)
        for renderer in STITCH_RENDERERS:
            self.renderer_combo.addItem(renderer.label, renderer.key)
        index = self.renderer_combo.findData(selected_renderer)
        self.renderer_combo.setCurrentIndex(max(0, index))
        self.renderer_combo.currentIndexChanged.connect(self._update_preview)
        layout.addWidget(self.renderer_combo)

        self.preview = QLabel(self)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(360, 220)
        layout.addWidget(self.preview, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self._accept_selection)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._update_preview()

    def _update_preview(self):
        renderer_key = self.renderer_combo.currentData()
        buffer = preview_stitches(renderer_key)
        height, width, channels = buffer.shape
        image = QImage(
            buffer.data,
            width,
            height,
            channels * width,
            QImage.Format_RGB888,
        ).copy()
        self.preview.setPixmap(QPixmap.fromImage(image))

    def _accept_selection(self):
        self.selected_renderer = self.renderer_combo.currentData()
        self.accept()
