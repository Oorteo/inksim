# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Interactive stitch timeline shown below the embroidery viewer."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QWheelEvent,
)
from PySide6.QtWidgets import QWidget

from .slider_controls import paint_background_slider

if TYPE_CHECKING:
    from .viewer import EmbroideryViewerWidget


class TimelineWidget(QWidget):
    """Interactive stitch timeline shown below the embroidery viewer."""

    seek_requested = Signal(int)
    MIN_WAVEFORM_SCALE_MM = 0.25
    MAX_WAVEFORM_SCALE_MM = 1000.0
    WAVEFORM_SCALE_STEP = 1.25
    BACKGROUND_WHEEL_STEP = 12

    def __init__(self, parent: QWidget, viewer_panel: EmbroideryViewerWidget) -> None:
        super().__init__(parent)
        self.viewer = viewer_panel
        self.setMinimumHeight(84)
        self.setStyleSheet("background: rgb(250, 250, 250)")
        self.setToolTip(
            "Drag BG from black to white to change the waveform background. "
            "Wheel over BG: adjust background; wheel over waveform: scale; "
            "Ctrl+wheel: zoom; Shift+wheel: pan."
        )
        self.dragging: str | None = None
        self.drag_moved = False
        self._overview_drag_offset = 0.0
        self._source_stitches = viewer_panel.stitches_np
        self._stitch_lengths_mm = self._calculate_stitch_lengths(viewer_panel.stitches_np)
        self.waveform_scale_mm = 5.0
        self.waveform_background = 230
        self._view_start = 0
        self._view_end = int(viewer_panel.stitches_np.shape[0])

    def _background_slider_rect(self) -> QRect:
        return QRect(25, 7, 52, 14)

    @staticmethod
    def _calculate_stitch_lengths(stitches: np.ndarray) -> np.ndarray:
        return np.hypot(
            stitches[:, 2] - stitches[:, 0],
            stitches[:, 3] - stitches[:, 1],
        )

    def _sync_view(self) -> int:
        stitches = self.viewer.stitches_np
        total = int(stitches.shape[0])
        if stitches is not self._source_stitches:
            self._source_stitches = stitches
            self._stitch_lengths_mm = self._calculate_stitch_lengths(stitches)
            self._view_start = 0
            self._view_end = total
        else:
            self._view_start = max(0, min(self._view_start, total))
            self._view_end = max(self._view_start + 1, min(self._view_end, total))
            if total == 0:
                self._view_start = self._view_end = 0
        return total

    def _layout_rects(self) -> tuple[QRect, QRect, tuple[QRect, QRect, QRect]]:
        main_bar = QRect(80, 7, max(1, self.width() - 88), 34)
        overview = QRect(80, 50, max(1, self.width() - 88), 8)
        buttons = (
            QRect(5, 26, 20, 17),
            QRect(28, 26, 20, 17),
            QRect(51, 26, 25, 17),
        )
        return main_bar, overview, buttons

    def _set_waveform_background_from_x(self, x: float) -> None:
        slider = self._background_slider_rect()
        ratio = max(0.0, min(1.0, (x - slider.left()) / max(1, slider.width() - 1)))
        self._set_waveform_background(int(round(ratio * 255)))

    def _set_waveform_background(self, value: int) -> None:
        self.waveform_background = max(0, min(255, value))
        self.setToolTip(
            f"Waveform background: {self.waveform_background}/255. "
            "Drag or wheel BG to change the background; wheel over the waveform changes scale."
        )
        self.update()

    def _set_view_start(self, start: int) -> None:
        total = self._sync_view()
        span = self._view_end - self._view_start
        self._view_start = max(0, min(start, max(0, total - span)))
        self._view_end = self._view_start + span
        self.update()

    def _zoom_at(self, mouse_x: float, factor: float) -> None:
        total = self._sync_view()
        if total <= 1:
            return
        main_bar, _, _ = self._layout_rects()
        old_span = self._view_end - self._view_start
        ratio = max(0.0, min(1.0, (mouse_x - main_bar.left()) / max(1, main_bar.width() - 1)))
        anchor = self._view_start + ratio * old_span
        new_span = max(1, min(total, int(round(old_span / factor))))
        new_start = int(round(anchor - ratio * new_span))
        self._view_start = max(0, min(new_start, total - new_span))
        self._view_end = self._view_start + new_span
        self.update()

    def _pan_overview_to(self, x: float) -> None:
        total = self._sync_view()
        if total == 0:
            return
        _, overview, _ = self._layout_rects()
        span = self._view_end - self._view_start
        start = int(
            round((x - self._overview_drag_offset - overview.left()) / overview.width() * total)
        )
        self._set_view_start(start)
        self._view_end = self._view_start + span

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return

        main_bar, overview, buttons = self._layout_rects()
        position = event.position()
        total = self._sync_view()
        if self._background_slider_rect().adjusted(0, -3, 0, 3).contains(position.toPoint()):
            self.dragging = "background"
            self.drag_moved = False
            self._set_waveform_background_from_x(position.x())
            self.grabMouse()
        elif buttons[0].contains(position.toPoint()):
            self._zoom_at(main_bar.center().x(), 1 / 1.25)
        elif buttons[1].contains(position.toPoint()):
            self._zoom_at(main_bar.center().x(), 1.25)
        elif buttons[2].contains(position.toPoint()):
            self._view_start = 0
            self._view_end = total
            self.update()
        elif main_bar.contains(position.toPoint()):
            self.dragging = "seek"
            self.drag_moved = False
            self.seek(position.x())
            self.viewer.highlight_needle()
            self.grabMouse()
        elif self._overview_interaction_rect(overview).contains(position.toPoint()):
            self.dragging = "overview"
            self.drag_moved = False
            viewport = self._overview_viewport(overview, total)
            viewport_frame = self._overview_viewport_frame(viewport)
            if viewport_frame.contains(position.toPoint()):
                self._overview_drag_offset = position.x() - viewport.left()
            else:
                self._overview_drag_offset = viewport.width() / 2
            self._pan_overview_to(position.x())
            self.grabMouse()
        else:
            super().mousePressEvent(event)
            return
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton and self.dragging is not None:
            if self.dragging == "seek":
                self.seek(event.position().x())
                self.viewer.highlight_needle()
            self.releaseMouse()
            self.dragging = None
            self.drag_moved = False
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self.dragging == "seek" and event.buttons() & Qt.LeftButton:
            self.drag_moved = True
            self.seek(event.position().x())
            event.accept()
        elif self.dragging == "overview" and event.buttons() & Qt.LeftButton:
            self.drag_moved = True
            self._pan_overview_to(event.position().x())
            event.accept()
        elif self.dragging == "background" and event.buttons() & Qt.LeftButton:
            self.drag_moved = True
            self._set_waveform_background_from_x(event.position().x())
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        modifiers = event.modifiers()
        delta = event.angleDelta().y()
        if not delta:
            delta = event.pixelDelta().y() * 8
        if modifiers & Qt.ControlModifier and delta:
            factor = 1.25 ** (delta / 120)
            self._zoom_at(event.position().x(), factor)
            event.accept()
        elif modifiers & Qt.ShiftModifier and delta:
            span = self._view_end - self._view_start
            self._set_view_start(self._view_start - int(round(span * delta / 120 * 0.1)))
            event.accept()
        elif (
            modifiers == Qt.NoModifier
            and delta
            and self._background_slider_rect()
            .adjusted(0, -3, 0, 3)
            .contains(event.position().toPoint())
        ):
            change = int(round(delta / 120 * self.BACKGROUND_WHEEL_STEP))
            if change == 0:
                change = 1 if delta > 0 else -1
            self._set_waveform_background(self.waveform_background + change)
            event.accept()
        elif (
            modifiers == Qt.NoModifier
            and delta
            and self._layout_rects()[0].contains(event.position().toPoint())
        ):
            scale_factor = self.WAVEFORM_SCALE_STEP ** (delta / 120)
            self.waveform_scale_mm = max(
                self.MIN_WAVEFORM_SCALE_MM,
                min(self.MAX_WAVEFORM_SCALE_MM, self.waveform_scale_mm / scale_factor),
            )
            self.update()
            event.accept()
        else:
            super().wheelEvent(event)

    def seek(self, mouse_x: float) -> None:
        total = self._sync_view()
        if total == 0:
            return
        main_bar, _, _ = self._layout_rects()
        ratio = max(0.0, min(1.0, (mouse_x - main_bar.left()) / max(1, main_bar.width() - 1)))
        self.seek_requested.emit(
            int(self._view_start + ratio * (self._view_end - self._view_start))
        )
        self.update()

    def _view_position_x(self, position: int, rect: QRect) -> int:
        span = self._view_end - self._view_start
        if span <= 0:
            return rect.left()
        ratio = max(0.0, min(1.0, (position - self._view_start) / span))
        return rect.left() + int(round(ratio * (rect.width() - 1)))

    def _overview_viewport(self, overview: QRect, total: int) -> QRect:
        if total == 0:
            return QRect()
        x0 = overview.left() + int(self._view_start / total * overview.width())
        x1 = overview.left() + int(self._view_end / total * overview.width())
        return QRect(x0, overview.top(), max(3, x1 - x0), overview.height())

    @staticmethod
    def _overview_interaction_rect(overview: QRect) -> QRect:
        return overview.adjusted(0, -6, 0, 6)

    @staticmethod
    def _overview_viewport_frame(viewport: QRect) -> QRect:
        return viewport.adjusted(0, -4, 0, 4)

    def _draw_stitch_colors(
        self,
        painter: QPainter,
        start: int,
        end: int,
        rect: QRect,
        stitches: np.ndarray,
    ) -> None:
        count = end - start
        if count <= 0:
            return
        painter.save()
        painter.setClipRect(rect)
        if rect.width() < count:
            step = max(1, count // max(1, rect.width()))
            for index in range(start, end, step):
                color = QColor(
                    int(stitches[index, 4]), int(stitches[index, 5]), int(stitches[index, 6])
                )
                x = rect.left() + int((index - start) / count * rect.width())
                painter.setPen(QPen(color))
                painter.drawLine(x, rect.top(), x, rect.bottom())
        else:
            last_color: tuple[int, int, int] | None = None
            block_start = start
            for index in range(start, end):
                rgb = tuple(int(value) for value in stitches[index, 4:7])
                assert len(rgb) == 3
                if rgb != last_color and last_color is not None:
                    x0 = rect.left() + int((block_start - start) / count * rect.width())
                    x1 = rect.left() + int((index - start) / count * rect.width())
                    color = QColor(*last_color)
                    painter.setBrush(color)
                    painter.setPen(QPen(color))
                    painter.drawRect(x0, rect.top(), max(1, x1 - x0), rect.height())
                    block_start = index
                last_color = rgb
            if last_color is not None:
                x0 = rect.left() + int((block_start - start) / count * rect.width())
                color = QColor(*last_color)
                painter.setBrush(color)
                painter.setPen(QPen(color))
                painter.drawRect(x0, rect.top(), max(1, rect.right() - x0 + 1), rect.height())
        painter.restore()

    @staticmethod
    def _stitch_waveform_amplitude(length_mm: float, half_height: float, scale_mm: float) -> float:
        """Map stitch length linearly to a clipped waveform amplitude."""
        length_mm = max(0.0, length_mm)
        fraction = min(1.0, length_mm / scale_mm)
        return max(1.0, half_height * fraction)

    def _draw_waveform_mark(
        self,
        painter: QPainter,
        x: int,
        length_mm: float,
        color: QColor,
        center_y: int,
        half_height: float,
        pen_width: int,
    ) -> None:
        amplitude = self._stitch_waveform_amplitude(length_mm, half_height, self.waveform_scale_mm)
        y_top = int(round(center_y - amplitude))
        y_bottom = int(round(center_y + amplitude))
        painter.setPen(QPen(color, pen_width))
        painter.drawLine(x, y_top, x, y_bottom)
        if length_mm > self.waveform_scale_mm:
            painter.setPen(QPen(color, pen_width))
            painter.drawLine(x - 2, y_top, x + 2, y_top)
            painter.drawLine(x - 2, y_bottom, x + 2, y_bottom)

    def _draw_stitch_waveform(
        self,
        painter: QPainter,
        start: int,
        end: int,
        rect: QRect,
        stitches: np.ndarray,
    ) -> None:
        count = end - start
        if count <= 0:
            return
        pixels_per_stitch = rect.width() / count
        center_y = rect.center().y()
        half_height = max(1.0, (rect.height() - 4) / 2)
        lengths_mm = self._stitch_lengths_mm[start:end]

        painter.save()
        painter.setClipRect(rect)
        painter.setPen(QPen(QColor(150, 150, 150), 1))
        painter.drawLine(rect.left(), center_y, rect.right(), center_y)
        if count <= rect.width():
            for index in range(start, end):
                x = self._view_position_x(index + 1, rect)
                color = QColor(*(int(value) for value in stitches[index, 4:7]))
                pen_width = max(1, min(2, int(round(pixels_per_stitch / 3))))
                self._draw_waveform_mark(
                    painter,
                    x,
                    float(lengths_mm[index - start]),
                    color,
                    center_y,
                    half_height,
                    pen_width,
                )
        else:
            bin_count = rect.width()
            bin_indices = np.rint(
                (np.arange(count, dtype=np.float64) + 1) * (bin_count - 1) / count
            ).astype(np.intp)
            peak_lengths = np.zeros(bin_count, dtype=lengths_mm.dtype)
            np.maximum.at(peak_lengths, bin_indices, lengths_mm)
            local_indices = np.arange(count, dtype=np.intp)
            peak_matches = lengths_mm == peak_lengths[bin_indices]
            peak_indices = np.full(bin_count, count, dtype=np.intp)
            np.minimum.at(
                peak_indices,
                bin_indices,
                np.where(peak_matches, local_indices, count),
            )
            for bin_index, peak_local_index in enumerate(peak_indices):
                if peak_local_index == count:
                    continue
                index = start + int(peak_local_index)
                color = QColor(*(int(value) for value in stitches[index, 4:7]))
                self._draw_waveform_mark(
                    painter,
                    rect.left() + bin_index,
                    float(peak_lengths[bin_index]),
                    color,
                    center_y,
                    half_height,
                    1,
                )
        painter.restore()

    def _draw_commands(
        self,
        painter: QPainter,
        rect: QRect,
        start: int,
        end: int,
        overview: bool = False,
    ) -> None:
        command_colors = {
            "JUMP": QColor(100, 100, 100),
            "COLOR CHANGE": QColor(210, 45, 45),
            "TRIM": QColor(230, 140, 20),
            "STOP": QColor(180, 40, 40),
            "SLOW": QColor(70, 100, 180),
            "FAST": QColor(40, 150, 90),
        }
        span = end - start
        painter.save()
        painter.setClipRect(rect)
        for stitch_index, commands in self.viewer.command_events.items():
            if not start <= stitch_index <= end:
                continue
            x = (
                rect.left() + int((stitch_index - start) / span * rect.width())
                if span
                else rect.left()
            )
            for marker_index, command in enumerate(commands):
                color = command_colors.get(command)
                if color is None and command.startswith("COLOR CHANGE"):
                    color = command_colors["COLOR CHANGE"]
                color = color or QColor(80, 80, 80)
                marker_y = rect.top() if overview else rect.top() + marker_index * 5
                painter.setPen(QPen(QColor(30, 30, 30), 1))
                painter.drawLine(x, marker_y, x, rect.bottom())
                if not overview:
                    painter.setBrush(color)
                    painter.drawPolygon(
                        [
                            QPoint(x, marker_y),
                            QPoint(x - 4, marker_y + 5),
                            QPoint(x + 4, marker_y + 5),
                        ]
                    )
        painter.restore()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor(250, 250, 250))
        total = self._sync_view()
        main_bar, overview, buttons = self._layout_rects()

        for rect, label in zip(buttons, ("−", "+", "All"), strict=True):
            painter.setBrush(QColor(245, 245, 245))
            painter.setPen(QPen(QColor(190, 190, 190)))
            painter.drawRoundedRect(rect, 2, 2)
            painter.setPen(QColor(35, 35, 35))
            painter.drawText(rect, Qt.AlignCenter, label)

        slider = self._background_slider_rect()
        painter.setPen(QColor(45, 45, 45))
        painter.drawText(QRect(3, 7, 20, 14), Qt.AlignCenter, "BG")
        paint_background_slider(painter, slider, self.waveform_background)

        background_color = QColor(
            self.waveform_background,
            self.waveform_background,
            self.waveform_background,
        )
        painter.setBrush(background_color)
        painter.setPen(QPen(QColor(128, 128, 128)))
        painter.drawRoundedRect(main_bar, 4, 4)
        painter.setBrush(QColor(230, 230, 230))
        painter.drawRect(overview)
        if total == 0:
            painter.end()
            return

        stitches = self.viewer.stitches_np
        self._draw_stitch_waveform(painter, self._view_start, self._view_end, main_bar, stitches)
        progress_ratio = max(
            0.0,
            min(
                1.0,
                (self.viewer.visible_count - self._view_start)
                / (self._view_end - self._view_start),
            ),
        )
        progress_width = int(progress_ratio * main_bar.width())
        painter.setBrush(QColor(255, 255, 255, 150))
        painter.setPen(Qt.NoPen)
        if progress_width < main_bar.width():
            painter.drawRect(
                main_bar.left() + progress_width,
                main_bar.top(),
                main_bar.width() - progress_width,
                main_bar.height(),
            )
        self._draw_commands(painter, main_bar, self._view_start, self._view_end)

        self._draw_stitch_colors(painter, 0, total, overview, stitches)
        self._draw_commands(painter, overview, 0, total, overview=True)
        viewport = self._overview_viewport(overview, total)
        viewport_frame = self._overview_viewport_frame(viewport)
        fog_color = QColor(250, 250, 250, 205)
        painter.setPen(Qt.NoPen)
        if viewport.left() > overview.left():
            painter.setBrush(fog_color)
            painter.drawRect(
                QRect(
                    overview.left(),
                    viewport_frame.top(),
                    viewport.left() - overview.left(),
                    viewport_frame.height(),
                )
            )
        if viewport.right() < overview.right():
            painter.setBrush(fog_color)
            painter.drawRect(
                QRect(
                    viewport.right() + 1,
                    viewport_frame.top(),
                    overview.right() - viewport.right(),
                    viewport_frame.height(),
                )
            )
        painter.setBrush(QColor(50, 115, 200, 45))
        painter.setPen(QPen(QColor(25, 75, 155), 2))
        painter.drawRect(viewport_frame)

        needle_x = overview.left() + int(
            max(0, min(total, self.viewer.visible_count)) / total * (overview.width() - 1)
        )
        needle_tip_y = overview.top() - 5
        painter.setPen(QPen(QColor(255, 255, 255), 4))
        painter.drawLine(needle_x, viewport_frame.top(), needle_x, viewport_frame.bottom())
        painter.setPen(QPen(QColor(210, 40, 50), 2))
        painter.drawLine(needle_x, viewport_frame.top(), needle_x, viewport_frame.bottom())
        painter.setBrush(QColor(210, 40, 50))
        painter.drawPolygon(
            [
                QPoint(needle_x, needle_tip_y),
                QPoint(needle_x - 4, needle_tip_y + 5),
                QPoint(needle_x + 4, needle_tip_y + 5),
            ]
        )

        if self._view_start <= self.viewer.visible_count <= self._view_end:
            knob_x = self._view_position_x(self.viewer.visible_count, main_bar)
            painter.setPen(QPen(QColor(40, 40, 40), 2))
            painter.setBrush(QColor(250, 250, 250))
            painter.drawEllipse(knob_x - 6, main_bar.center().y() - 6, 12, 12)
            painter.setBrush(QColor(40, 40, 40))
            painter.drawEllipse(knob_x - 3, main_bar.center().y() - 3, 6, 6)

        visible = self.viewer.visible_count
        txt_left = f"{visible}/{total}"
        if visible > 0:
            last_stitch = stitches[visible - 1]
            dx = float(last_stitch[2] - last_stitch[0])
            dy = float(last_stitch[3] - last_stitch[1])
            last_step_mm = (dx * dx + dy * dy) ** 0.5
            txt_left += f" | [{last_step_mm:.2f} mm]"
        stitches_per_minute = (
            int(round(self.viewer.play_step / self.viewer.play_speed * 60000))
            if self.viewer.play_speed > 0
            else 0
        )
        txt_left += f" | {stitches_per_minute} stitches/min"
        visible_commands: list[str] | tuple[()] = self.viewer.command_events.get(visible, ())
        if visible_commands:
            txt_left += f" | {' | '.join(visible_commands)}"
        txt_center = f"{visible / total * 100:.1f}%"
        if self.viewer.bounds != (0, 0, 0, 0):
            bounds = self.viewer.bounds
            txt_right = (
                f"{bounds[2] - bounds[0]:.1f} x {bounds[3] - bounds[1]:.1f} mm | "
                f"{self.viewer.color_count} color sections | "
                f"waveform ≤ {self.waveform_scale_mm:g} mm | "
                f"BG {self.waveform_background}/255"
            )
        else:
            txt_right = (
                f"waveform ≤ {self.waveform_scale_mm:g} mm | BG {self.waveform_background}/255"
            )
        font_metrics = painter.fontMetrics()
        text_top = 64
        text_height = font_metrics.height()
        bar_width = main_bar.width()
        left_width = int(bar_width * 0.45)
        center_width = int(bar_width * 0.15)
        right_width = bar_width - left_width - center_width
        left_rect = QRect(main_bar.left(), text_top, left_width, text_height)
        center_rect = QRect(main_bar.left() + left_width, text_top, center_width, text_height)
        right_rect = QRect(
            main_bar.left() + left_width + center_width, text_top, right_width, text_height
        )
        painter.setPen(QColor(30, 30, 30))
        painter.drawText(
            left_rect,
            Qt.AlignLeft | Qt.AlignVCenter,
            font_metrics.elidedText(txt_left, Qt.ElideRight, left_width),
        )
        painter.drawText(
            center_rect,
            Qt.AlignCenter | Qt.AlignVCenter,
            font_metrics.elidedText(txt_center, Qt.ElideRight, center_width),
        )
        if txt_right:
            painter.drawText(
                right_rect,
                Qt.AlignRight | Qt.AlignVCenter,
                font_metrics.elidedText(txt_right, Qt.ElideRight, right_width),
            )
        painter.end()
