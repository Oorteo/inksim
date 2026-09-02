# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
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

from ..constants import (
    NEEDLE_RADIUS_MAX,
    NEEDLE_RADIUS_MIN,
    NEEDLE_WIDTH_MAX,
    NEEDLE_WIDTH_MIN,
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


class _NeedlePopup(QMenu):
    """Popup with sliders for needle radius, width, color and fullscreen."""

    def __init__(self, parent, viewer):
        super().__init__(parent)
        self.viewer = viewer
        self._sliders = {}
        self._labels = {}

        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Two vertical sliders side by side (radius + width).
        sliders_row = QHBoxLayout()
        sliders_row.setSpacing(12)

        # Radius slider.
        radius_col = QVBoxLayout()
        radius_col.setSpacing(4)
        radius_title = QLabel("Radius")
        radius_title.setAlignment(Qt.AlignCenter)
        radius_col.addWidget(radius_title)
        radius_slider = QSlider(Qt.Vertical)
        radius_slider.setRange(0, 1000)
        radius_slider.setFixedHeight(140)
        radius_slider.setValue(self._to_slider(
            viewer.needle_radius, NEEDLE_RADIUS_MIN, NEEDLE_RADIUS_MAX))
        radius_slider.valueChanged.connect(
            lambda v: self._apply_radius(v))
        radius_col.addWidget(radius_slider, alignment=Qt.AlignCenter)
        self._radius_label = QLabel()
        self._radius_label.setAlignment(Qt.AlignCenter)
        radius_col.addWidget(self._radius_label)
        sliders_row.addLayout(radius_col)

        # Width slider.
        width_col = QVBoxLayout()
        width_col.setSpacing(4)
        width_title = QLabel("Width")
        width_title.setAlignment(Qt.AlignCenter)
        width_col.addWidget(width_title)
        width_slider = QSlider(Qt.Vertical)
        width_slider.setRange(0, 1000)
        width_slider.setFixedHeight(140)
        width_slider.setValue(self._to_slider(
            viewer.needle_width, NEEDLE_WIDTH_MIN, NEEDLE_WIDTH_MAX))
        width_slider.valueChanged.connect(
            lambda v: self._apply_width(v))
        width_col.addWidget(width_slider, alignment=Qt.AlignCenter)
        self._width_label = QLabel()
        self._width_label.setAlignment(Qt.AlignCenter)
        width_col.addWidget(self._width_label)
        sliders_row.addLayout(width_col)

        layout.addLayout(sliders_row)

        # Color button.
        color_button = QPushButton("Color…")
        color_button.clicked.connect(self._choose_color)
        layout.addWidget(color_button)

        # Fullscreen checkbox.
        self._fullscreen_check = QCheckBox("Full screen")
        self._fullscreen_check.setChecked(viewer.needle_fullscreen)
        self._fullscreen_check.toggled.connect(self._toggle_fullscreen)
        layout.addWidget(self._fullscreen_check)

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

    def _apply_radius(self, value):
        self.viewer.needle_radius = self._from_slider(
            value, NEEDLE_RADIUS_MIN, NEEDLE_RADIUS_MAX)
        self.viewer._save_view_setting("view/needle_radius", self.viewer.needle_radius)
        self._refresh_labels()
        self.viewer.update()

    def _apply_width(self, value):
        self.viewer.needle_width = self._from_slider(
            value, NEEDLE_WIDTH_MIN, NEEDLE_WIDTH_MAX)
        self.viewer._save_view_setting("view/needle_width", self.viewer.needle_width)
        self._refresh_labels()
        self.viewer.update()

    def _choose_color(self):
        from PySide6.QtWidgets import QColorDialog
        original_color = self.viewer.needle_color
        dialog = QColorDialog(QColor(*original_color), self)
        dialog.setWindowTitle("Needle color")

        def _on_preview(color):
            if color.isValid():
                self.viewer.needle_color = (color.red(), color.green(), color.blue())
                self.viewer.update()

        dialog.currentColorChanged.connect(_on_preview)

        if not dialog.exec():
            # Cancelled: restore the original color.
            self.viewer.needle_color = original_color
            self.viewer.update()
            return

        chosen = dialog.selectedColor()
        if not chosen.isValid():
            return
        self.viewer.needle_color = (chosen.red(), chosen.green(), chosen.blue())
        self.viewer._save_view_setting(
            "view/needle_color", list(self.viewer.needle_color))
        self.viewer.update()

    def _toggle_fullscreen(self, checked):
        self.viewer.needle_fullscreen = checked
        self.viewer._save_view_setting("view/needle_fullscreen", checked)
        self.viewer.update()

    def _refresh_labels(self):
        self._radius_label.setText(f"{self.viewer.needle_radius:.0f}")
        self._width_label.setText(f"{self.viewer.needle_width:.1f}")


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
            "E": "Reverse stitch drawing order",
            "J": "Cycle jump display: off, all, risky only",
            "V": "Toggle stitch visibility",
            "B": "Cycle background: black, white, configured",
        }
        for mode in ("Z", "X", "E", "J", "V", "B"):
            button = QPushButton(mode, self)
            button.setFixedSize(32, 32)
            button.setToolTip(tooltips[mode])
            button.clicked.connect(lambda checked=False, m=mode: self.toggle_mode(m))
            self.buttons[mode] = button
            sizer.addWidget(button)
        sizer.addStretch()
        # Needle settings button (cross symbol), on the right before DF/LF/LW.
        self.needle_button = QPushButton("✛", self)
        self.needle_button.setFixedSize(32, 32)
        self.needle_button.setToolTip("Needle crosshair settings")
        self.needle_button.clicked.connect(self._show_needle_popup)
        sizer.addWidget(self.needle_button)
        self.needle_reset_button = QPushButton(self)
        self.needle_reset_button.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))
        self.needle_reset_button.setToolTip("Reset needle settings")
        self.needle_reset_button.setFixedSize(32, 32)
        self.needle_reset_button.clicked.connect(self._reset_needle)
        sizer.addWidget(self.needle_reset_button)
        self.settings_button = QPushButton(self)
        self.settings_button.setMinimumWidth(180)
        self.settings_button.setToolTip(
            "Click to adjust dark factor, light factor and line width"
        )
        self.settings_button.clicked.connect(self._show_sliders)
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

    def _show_needle_popup(self):
        popup = _NeedlePopup(self, self.viewer)
        popup.exec(self.needle_button.mapToGlobal(
            self.needle_button.rect().bottomLeft()
        ))

    def _reset_needle(self):
        from ..constants import (
            DEFAULT_NEEDLE_COLOR,
            DEFAULT_NEEDLE_RADIUS,
            DEFAULT_NEEDLE_WIDTH,
        )
        self.viewer.needle_color = DEFAULT_NEEDLE_COLOR
        self.viewer.needle_radius = DEFAULT_NEEDLE_RADIUS
        self.viewer.needle_width = DEFAULT_NEEDLE_WIDTH
        self.viewer.needle_fullscreen = False
        self.viewer._save_view_setting("view/needle_color", list(DEFAULT_NEEDLE_COLOR))
        self.viewer._save_view_setting("view/needle_radius", DEFAULT_NEEDLE_RADIUS)
        self.viewer._save_view_setting("view/needle_width", DEFAULT_NEEDLE_WIDTH)
        self.viewer._save_view_setting("view/needle_fullscreen", False)
        self.viewer.update()

    def update_indicators(self):
        self.settings_button.setText(
            f"DF: {self.viewer.dark_factor:.2f}  "
            f"LF: {self.viewer.light_factor:.2f}  "
            f"LW: {self.viewer.line_width:.2f}"
        )
        states = {
            "Z": self.viewer.active_renderer == "gpu_textured",
            "X": self.viewer.show_density,
            "E": self.viewer.reverse_stitch_order,
            "V": self.viewer.show_stitches,
        }
        jump_state = 0
        if self.viewer.show_jumps:
            jump_state = 2 if self.viewer.risky_jumps_only else 1
        for mode, button in self.buttons.items():
            state = (
                jump_state if mode == "J"
                else self.viewer.background_cycle if mode == "B"
                else int(states[mode])
            )
            if mode == "J" and state == 2:
                color = QColor(210, 145, 45)
            elif mode == "E" and state:
                color = QColor(190, 55, 45)
            elif mode == "B" and state == 1:
                color = QColor(45, 45, 45)
            elif mode == "B" and state == 2:
                color = QColor(245, 245, 245)
            elif state:
                color = QColor(75, 140, 90)
            else:
                color = QColor(225, 225, 225)
            foreground = (
                "white" if (mode == "B" and state == 1) or (state and mode != "B")
                else "rgb(45, 45, 45)"
            )
            button.setStyleSheet(
                f"background: {color.name()}; color: {foreground};"
            )
