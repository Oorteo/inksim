from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

class ModeBar(QWidget):
    """Clickable indicators for the main viewer display modes."""

    def __init__(self, parent, viewer):
        super().__init__(parent)
        self.viewer = viewer
        self.setFixedHeight(38)
        self.setStyleSheet("background: rgb(245, 245, 245)")
        sizer = QHBoxLayout(self)
        sizer.setContentsMargins(4, 3, 4, 3)
        self.buttons = {}
        for mode in ("R", "X", "J", "V"):
            button = QPushButton(mode, self)
            button.setFixedSize(32, 32)
            button.clicked.connect(lambda checked=False, m=mode: self.toggle_mode(m))
            self.buttons[mode] = button
            sizer.addWidget(button)
        sizer.addStretch()
        self.update_indicators()

    def toggle_mode(self, mode):
        self.viewer.toggle_display_mode(mode)
        self.viewer.setFocus()

    def update_indicators(self):
        states = {
            "R": self.viewer.show_realistic,
            "X": self.viewer.show_density,
            "V": self.viewer.show_stitches,
        }
        jump_state = 0
        if self.viewer.show_jumps:
            jump_state = 2 if self.viewer.risky_jumps_only else 1
        for mode, button in self.buttons.items():
            state = jump_state if mode == "J" else int(states[mode])
            if mode == "J" and state == 2:
                color = QColor(210, 145, 45)
            elif state:
                color = QColor(75, 140, 90)
            else:
                color = QColor(225, 225, 225)
            foreground = "white" if state else "rgb(45, 45, 45)"
            button.setStyleSheet(
                f"background: {color.name()}; color: {foreground};"
            )
