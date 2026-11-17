# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Small custom-painted sliders used by the viewer and file browser."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import (
    QColor,
    QLinearGradient,
    QPainter,
    QPaintEvent,
    QPalette,
    QPen,
    QPolygon,
)
from PySide6.QtWidgets import (
    QSlider,
    QStyle,
    QStyleOptionFocusRect,
    QStyleOptionSlider,
    QWidget,
)


def paint_background_slider(
    painter: QPainter,
    slider: QRect,
    value: int,
    minimum: int = 0,
    maximum: int = 255,
    *,
    position_x: int | None = None,
) -> None:
    """Paint the black-to-white background control shared with the timeline."""
    span = maximum - minimum
    ratio = 0.0 if span <= 0 else max(0.0, min(1.0, (value - minimum) / span))
    gradient = QLinearGradient(slider.left(), slider.top(), slider.right(), slider.top())
    gradient.setColorAt(0, QColor(0, 0, 0))
    gradient.setColorAt(1, QColor(255, 255, 255))
    painter.save()
    painter.setBrush(gradient)
    painter.setPen(QPen(QColor(90, 90, 90), 1))
    painter.drawRoundedRect(slider, 3, 3)
    slider_x = (
        position_x
        if position_x is not None
        else slider.left() + int(round(ratio * (slider.width() - 1)))
    )
    painter.setBrush(QColor(255, 255, 255))
    painter.setPen(QPen(QColor(20, 20, 20), 1))
    painter.drawEllipse(slider_x - 4, slider.center().y() - 5, 9, 10)
    painter.restore()


def paint_icon_size_slider(
    painter: QPainter,
    slider: QRect,
    value: int,
    minimum: int,
    maximum: int,
    *,
    position_x: int | None = None,
) -> None:
    """Paint a wedge that widens to indicate increasing icon size."""
    span = maximum - minimum
    ratio = 0.0 if span <= 0 else max(0.0, min(1.0, (value - minimum) / span))
    center_y = slider.center().y()
    slider_x = (
        position_x
        if position_x is not None
        else slider.left() + int(round(ratio * (slider.width() - 1)))
    )
    wedge = QPolygon(
        [
            QPoint(slider.left(), center_y - 1),
            QPoint(slider.right(), center_y - 7),
            QPoint(slider.right(), center_y + 7),
            QPoint(slider.left(), center_y + 1),
        ]
    )
    painter.save()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(155, 165, 178))
    painter.drawPolygon(wedge)
    painter.setBrush(QColor(255, 255, 255))
    painter.setPen(QPen(QColor(20, 20, 20), 1))
    painter.drawEllipse(slider_x - 4, center_y - 5, 9, 10)
    painter.restore()


class _PaintedSlider(QSlider):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setMinimumHeight(28)

    def paintEvent(self, _event: QPaintEvent) -> None:
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        style = self.style()
        groove = style.subControlRect(
            QStyle.ComplexControl.CC_Slider,
            option,
            QStyle.SubControl.SC_SliderGroove,
            self,
        )
        handle = style.subControlRect(
            QStyle.ComplexControl.CC_Slider,
            option,
            QStyle.SubControl.SC_SliderHandle,
            self,
        )
        half_handle = handle.width() // 2
        left = groove.left() + half_handle
        right = groove.right() - half_handle
        if right < left:
            left, right = groove.left(), groove.right()
        track = QRect(left, self.height() // 2 - 7, max(1, right - left + 1), 14)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(self.palette().color(QPalette.ColorRole.Highlight), 1))
        self._paint_track(painter, track, handle.center().x())
        if self.hasFocus():
            focus = QStyleOptionFocusRect()
            focus.initFrom(self)
            focus.rect = self.rect().adjusted(1, 1, -1, -1)
            focus.backgroundColor = self.palette().color(QPalette.ColorRole.Window)
            style.drawPrimitive(
                QStyle.PrimitiveElement.PE_FrameFocusRect,
                focus,
                painter,
                self,
            )

    def _paint_track(self, painter: QPainter, track: QRect, position_x: int) -> None:
        raise NotImplementedError


class BackgroundValueSlider(_PaintedSlider):
    def _paint_track(self, painter: QPainter, track: QRect, position_x: int) -> None:
        paint_background_slider(
            painter,
            track,
            self.value(),
            self.minimum(),
            self.maximum(),
            position_x=position_x,
        )


class IconSizeSlider(_PaintedSlider):
    def _paint_track(self, painter: QPainter, track: QRect, position_x: int) -> None:
        paint_icon_size_slider(
            painter,
            track,
            self.value(),
            self.minimum(),
            self.maximum(),
            position_x=position_x,
        )
