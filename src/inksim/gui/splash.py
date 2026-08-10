from pathlib import Path
from time import monotonic

from PySide6.QtCore import Qt, QThread, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ..render import (
    render_fabric_numba,
    render_grid_numba,
    render_realistic_numba,
    render_shaded_numba,
)


class RendererWarmupThread(QThread):
    """Compile the first-use Numba renderers away from the Qt GUI thread."""

    def run(self):
        import numpy as np

        buffer = np.full((16, 16, 3), 255, dtype=np.uint8)
        stitches = np.array(
            [(0, 0, 5, 5, 40, 150, 90)],
            dtype=np.float32,
        )
        render_grid_numba(buffer, 1.0, 8.0, 8.0)
        render_shaded_numba(
            buffer, stitches, 1, 1.0, 8.0, 8.0, True, 0.4, 0.75, 0.45
        )
        render_realistic_numba(
            buffer, stitches, 1, 1.0, 8.0, 8.0, 0.4, 0.75, 0.45
        )
        render_fabric_numba(buffer, 1.0)


class LoadingSpinner(QWidget):
    """Small animated activity indicator for the startup splash."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(32, 32)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance)

    def start(self):
        self._timer.start(80)
        self.update()

    def stop(self):
        self._timer.stop()

    def _advance(self):
        self._angle = (self._angle + 30) % 360
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.translate(self.width() / 2, self.height() / 2)
        painter.rotate(self._angle)
        for index in range(8):
            opacity = 40 + index * 25
            painter.save()
            painter.rotate(index * 45)
            painter.setPen(QPen(QColor(66, 184, 131, opacity), 3))
            painter.drawLine(0, -5, 0, -12)
            painter.restore()
        painter.end()


class SplashScreen(QWidget):
    """Small frameless startup window with an activity indicator."""

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

        self.spinner = LoadingSpinner(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 10)
        layout.setSpacing(8)
        layout.addWidget(self.logo)
        layout.addWidget(self.status)
        layout.addWidget(self.spinner, alignment=Qt.AlignCenter)
        self.adjustSize()
        self._shown_at = None

    def set_message(self, message):
        self.status.setText(message)
        QApplication.processEvents()

    def show_centered(self):
        screen = QApplication.primaryScreen()
        if screen is not None:
            self.move(screen.availableGeometry().center() - self.rect().center())
        self.show()
        self._shown_at = monotonic()
        self.spinner.start()
        QApplication.processEvents()

    def close_after(self, minimum_ms=1500):
        """Close after the minimum visible time has elapsed."""
        if self._shown_at is None:
            self.close()
            return
        elapsed_ms = int((monotonic() - self._shown_at) * 1000)
        QTimer.singleShot(max(0, minimum_ms - elapsed_ms), self.close)

    def closeEvent(self, event):
        self.spinner.stop()
        event.accept()
