from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QStyle, QWidget

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
        for mode in ("Z", "X", "J", "V"):
            button = QPushButton(mode, self)
            button.setFixedSize(32, 32)
            button.clicked.connect(lambda checked=False, m=mode: self.toggle_mode(m))
            self.buttons[mode] = button
            sizer.addWidget(button)
        self.settings_label = QLabel(self)
        self.settings_label.setMinimumWidth(180)
        sizer.addStretch()
        sizer.addWidget(self.settings_label)
        self.reset_button = QPushButton(self)
        self.reset_button.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))
        self.reset_button.setToolTip("Reset line width and shading factors")
        self.reset_button.setFixedSize(32, 32)
        self.reset_button.clicked.connect(self.viewer.reset_render_settings)
        sizer.addWidget(self.reset_button)
        self.update_indicators()

    def toggle_mode(self, mode):
        self.viewer.toggle_display_mode(mode)
        self.viewer.setFocus()

    def update_indicators(self):
        self.settings_label.setText(
            f"DF: {self.viewer.dark_factor:.2f}  "
            f"LF: {self.viewer.light_factor:.2f}  "
            f"LW: {self.viewer.line_width:.2f}"
        )
        states = {
            "Z": self.viewer.show_realistic,
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
