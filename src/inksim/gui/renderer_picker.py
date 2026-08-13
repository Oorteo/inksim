"""Renderer selection dialog with a live representative preview."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QHBoxLayout,
    QVBoxLayout,
)

from ..render import STITCH_RENDERERS, preview_stitches


class RendererPickerDialog(QDialog):
    """Choose a stitch renderer and preview its output."""

    def __init__(self, parent, selected_renderer):
        super().__init__(parent)
        self.setWindowTitle("Choose stitch renderer")
        self.resize(760, 460)
        self.selected_renderer = selected_renderer
        layout = QVBoxLayout(self)
        content = QHBoxLayout()
        layout.addLayout(content, 1)

        self.renderer_list = QListWidget(self)
        self.renderer_list.setMinimumWidth(150)
        for renderer in STITCH_RENDERERS:
            item = QListWidgetItem(renderer.label, self.renderer_list)
            item.setData(Qt.UserRole, renderer.key)
        index = next(
            (index for index, renderer in enumerate(STITCH_RENDERERS)
             if renderer.key == selected_renderer),
            0,
        )
        self.renderer_list.setCurrentRow(index)
        self.renderer_list.currentRowChanged.connect(self._update_preview)
        content.addWidget(self.renderer_list)

        self.preview = QLabel(self)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(540, 320)
        content.addWidget(self.preview, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self._accept_selection)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        ok_button.setDefault(True)
        ok_button.setAutoDefault(True)
        cancel_button.setDefault(False)
        cancel_button.setAutoDefault(False)
        self.setTabOrder(self.renderer_list, ok_button)
        self.setTabOrder(ok_button, cancel_button)
        self._confirm_shortcut = QShortcut(QKeySequence("Ctrl+Return"), self)
        self._confirm_shortcut.setContext(Qt.WindowShortcut)
        self._confirm_shortcut.activated.connect(self._accept_selection)
        self._update_preview()

    def _update_preview(self):
        item = self.renderer_list.currentItem()
        if item is None:
            return
        renderer_key = item.data(Qt.UserRole)
        self.preview.setPixmap(QPixmap.fromImage(preview_stitches(renderer_key)))

    def _accept_selection(self):
        item = self.renderer_list.currentItem()
        if item is not None:
            self.selected_renderer = item.data(Qt.UserRole)
        self.accept()
