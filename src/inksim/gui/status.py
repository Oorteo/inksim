from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSlider,
    QStyle,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)


class _SliderPopup(QMenu):
    """Popup with vertical sliders for DF / LF / LW tuning."""

    def __init__(self, parent, viewer):
        super().__init__(parent)
        self.viewer = viewer
        self._sliders = {}
        self._labels = {}

        container = QWidget(self)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)

        specs = (
            ("DF", "dark_factor", 0.0, 1.0),
            ("LF", "light_factor", 0.0, 1.0),
            ("LW", "line_width", 0.1, 1.0),
        )
        for name, attr, lo, hi in specs:
            column = QVBoxLayout()
            column.setSpacing(4)
            title = QLabel(name)
            title.setAlignment(Qt.AlignCenter)
            column.addWidget(title)

            slider = QSlider(Qt.Vertical)
            slider.setRange(0, 1000)
            slider.setFixedHeight(140)
            slider.setValue(self._to_slider(getattr(viewer, attr), lo, hi))
            slider.valueChanged.connect(
                lambda value, a=attr, l=lo, h=hi: self._apply(a, value, l, h)
            )
            column.addWidget(slider, alignment=Qt.AlignCenter)

            value_label = QLabel()
            value_label.setAlignment(Qt.AlignCenter)
            value_label.setMinimumWidth(40)
            column.addWidget(value_label)

            self._sliders[attr] = slider
            self._labels[attr] = value_label
            layout.addLayout(column)

        self._refresh_labels()

        action = QWidgetAction(self)
        action.setDefaultWidget(container)
        self.addAction(action)

    @staticmethod
    def _to_slider(value, lo, hi):
        return int(round((value - lo) / (hi - lo) * 1000))

    @staticmethod
    def _from_slider(value, lo, hi):
        return lo + (value / 1000.0) * (hi - lo)

    def _apply(self, attr, value, lo, hi):
        setattr(self.viewer, attr, self._from_slider(value, lo, hi))
        self._refresh_labels()
        self.viewer.invalidate_cache()
        self.viewer.update()
        self.viewer.update_mode_indicators()

    def _refresh_labels(self):
        for attr, label in self._labels.items():
            label.setText(f"{getattr(self.viewer, attr):.2f}")


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
        tooltips = {
            "Z": "Toggle GPU textured rendering",
            "X": "Toggle stitch density overlay",
            "J": "Cycle jump display: off, all, risky only",
            "V": "Toggle stitch visibility",
        }
        for mode in ("Z", "X", "J", "V"):
            button = QPushButton(mode, self)
            button.setFixedSize(32, 32)
            button.setToolTip(tooltips[mode])
            button.clicked.connect(lambda checked=False, m=mode: self.toggle_mode(m))
            self.buttons[mode] = button
            sizer.addWidget(button)
        self.settings_button = QPushButton(self)
        self.settings_button.setMinimumWidth(180)
        self.settings_button.setToolTip(
            "Click to adjust dark factor, light factor and line width"
        )
        self.settings_button.clicked.connect(self._show_sliders)
        sizer.addStretch()
        sizer.addWidget(self.settings_button)
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

    def _show_sliders(self):
        popup = _SliderPopup(self, self.viewer)
        popup.exec(self.settings_button.mapToGlobal(
            self.settings_button.rect().bottomLeft()
        ))

    def update_indicators(self):
        self.settings_button.setText(
            f"DF: {self.viewer.dark_factor:.2f}  "
            f"LF: {self.viewer.light_factor:.2f}  "
            f"LW: {self.viewer.line_width:.2f}"
        )
        states = {
            "Z": self.viewer.active_renderer == "gpu_textured",
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
