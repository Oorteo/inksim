from PySide6.QtWidgets import QWidget


class EmbroideryFileDropTarget(QWidget):
    """Open the first dropped file in the owning frame."""

    def __init__(self, frame):
        super().__init__(frame)
        self.frame = frame

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            self.frame.OpenFile(urls[0].toLocalFile())
            event.acceptProposedAction()
