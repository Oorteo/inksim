from pathlib import Path
from time import monotonic

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)


class SplashScreen(QWidget):
    """Small frameless startup window for loading and batch progress."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.SplashScreen
            | Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setStyleSheet(
            "background: #faf8f4;"
            "border: 1px solid #c8c4bc;"
            "border-radius: 8px;"
        )
        self.setWindowTitle("InkSim")

        self.logo = QLabel(self)
        self.logo.setAttribute(Qt.WA_TranslucentBackground)
        self.logo.setStyleSheet("background: transparent;")
        asset_path = Path(__file__).parent.parent / "assets" / "InkSim_colorful_small.png"
        self.logo.setPixmap(QPixmap(str(asset_path)))
        self.logo.setAlignment(Qt.AlignCenter)

        self.status = QLabel("Starting InkSim...", self)
        self.status.setAlignment(Qt.AlignCenter)
        self.status.setStyleSheet(
            "color: #343434; background: rgba(255, 255, 255, 180); "
            "border: 0; padding: 5px 10px;"
        )

        self.progress = QProgressBar(self)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(8)
        self.progress.setStyleSheet(
            "QProgressBar { background: #dedbd5; border: 0; }"
            "QProgressBar::chunk { background: #42b883; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 10)
        layout.setSpacing(8)
        layout.addWidget(self.logo)
        layout.addWidget(self.status)
        layout.addWidget(self.progress)
        self.adjustSize()
        self._shown_at = None

    def set_progress(self, value, message):
        self.progress.setValue(max(0, min(100, value)))
        self.status.setText(message)
        QApplication.processEvents()

    def show_centered(self):
        screen = QApplication.primaryScreen()
        if screen is not None:
            self.move(screen.availableGeometry().center() - self.rect().center())
        self.show()
        self._shown_at = monotonic()
        QApplication.processEvents()

    def close_after(self, minimum_ms=1500):
        """Close after the minimum visible time has elapsed."""
        if self._shown_at is None:
            self.close()
            return
        elapsed_ms = int((monotonic() - self._shown_at) * 1000)
        QTimer.singleShot(max(0, minimum_ms - elapsed_ms), self.close)
