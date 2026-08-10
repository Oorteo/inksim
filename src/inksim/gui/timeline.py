from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


class ProgressBarPanel(QWidget):
    """Interactive stitch timeline shown below the embroidery viewer."""

    def __init__(self, parent, viewer_panel):
        super().__init__(parent)
        self.viewer = viewer_panel
        self.setMinimumHeight(58)
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self.setAutoFillBackground(True)
        self.setStyleSheet("background: rgb(250, 250, 250)")
        self.dragging = False
        self.drag_moved = False
        self.margin_x = 24
        self.bar_y = 8
        self.bar_h = 14

    def OnEraseBackground(self, event):
        pass

    def OnClick(self, event):
        self.dragging = True
        self.drag_moved = False
        self.Seek(event.position().x())
        self.viewer.HighlightNeedle()
        self.grabMouse()

    def OnLeftUp(self, event):
        if self.dragging:
            self.Seek(event.position().x())
            self.viewer.HighlightNeedle()
            self.releaseMouse()
            self.dragging = False
            self.drag_moved = False

    def OnMotionClick(self, event):
        if self.dragging and event.buttons() & Qt.LeftButton:
            self.drag_moved = True
            self.Seek(event.position().x())

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.OnClick(event)
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.OnLeftUp(event)
        else:
            super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        self.OnMotionClick(event)
        super().mouseMoveEvent(event)

    def Seek(self, mouse_x):
        width = self.width()
        total = self.viewer.stitches_np.shape[0]
        if total == 0 or width == 0:
            return
        bar_width = width - 2 * self.margin_x
        ratio = max(0.0, min(1.0, (mouse_x - self.margin_x) / bar_width
                             if bar_width > 0 else 0))
        self.viewer.visible_count = int(ratio * total)
        self.viewer.need_redraw = True
        self.viewer.update()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor(250, 250, 250))
        width = self.width()
        total = self.viewer.stitches_np.shape[0]
        visible = self.viewer.visible_count
        bar_x = self.margin_x
        bar_width = width - 2 * self.margin_x
        bar_rect = self.rect().adjusted(bar_x, self.bar_y, -bar_x, 0)
        bar_rect.setHeight(self.bar_h)
        painter.setBrush(QColor(230, 230, 230))
        painter.setPen(QPen(QColor(200, 200, 200)))
        painter.drawRoundedRect(bar_rect, 4, 4)
        if total == 0:
            painter.end()
            return

        stitches = self.viewer.stitches_np
        painter.save()
        painter.setClipRect(bar_rect)
        if bar_width < total:
            step = max(1, total // max(1, bar_width))
            for index in range(0, total, step):
                color = QColor(int(stitches[index, 4]), int(stitches[index, 5]),
                               int(stitches[index, 6]))
                x = bar_x + int(index / total * bar_width)
                painter.setPen(QPen(color))
                painter.drawLine(x, self.bar_y, x, self.bar_y + self.bar_h)
        else:
            last_color = None
            block_start = 0
            for index in range(total):
                color = tuple(int(value) for value in stitches[index, 4:7])
                if color != last_color and last_color is not None:
                    x0 = bar_x + int(block_start / total * bar_width)
                    x1 = bar_x + int(index / total * bar_width)
                    qcolor = QColor(*last_color)
                    painter.setBrush(qcolor)
                    painter.setPen(QPen(qcolor))
                    painter.drawRect(x0, self.bar_y, max(2, x1 - x0), self.bar_h)
                    block_start = index
                last_color = color
            if last_color:
                x0 = bar_x + int(block_start / total * bar_width)
                qcolor = QColor(*last_color)
                painter.setBrush(qcolor)
                painter.setPen(QPen(qcolor))
                painter.drawRect(x0, self.bar_y, bar_width - (x0 - bar_x), self.bar_h)

        command_colors = {
            "JUMP": QColor(100, 100, 100), "COLOR CHANGE": QColor(210, 45, 45),
            "TRIM": QColor(230, 140, 20), "STOP": QColor(180, 40, 40),
            "SLOW": QColor(70, 100, 180), "FAST": QColor(40, 150, 90),
        }
        for stitch_index, commands in self.viewer.command_events.items():
            marker_x = bar_x + int(stitch_index / total * bar_width)
            for marker_index, command in enumerate(commands):
                color = command_colors.get(command)
                if color is None and command.startswith("COLOR CHANGE"):
                    color = command_colors["COLOR CHANGE"]
                color = color or QColor(80, 80, 80)
                painter.setBrush(color)
                painter.setPen(QPen(color))
                marker_y = self.bar_y + marker_index * 5
                painter.drawPolygon([
                    QPoint(marker_x, marker_y),
                    QPoint(marker_x - 4, marker_y + 5),
                    QPoint(marker_x + 4, marker_y + 5),
                ])
        progress_width = int(visible / total * bar_width)
        painter.setBrush(QColor(255, 255, 255, 150))
        painter.setPen(Qt.NoPen)
        if progress_width < bar_width:
            painter.drawRect(bar_x + progress_width, self.bar_y,
                             bar_width - progress_width, self.bar_h)
        painter.restore()

        knob_x = bar_x + progress_width
        painter.setPen(QPen(QColor(40, 40, 40), 2))
        painter.setBrush(QColor(250, 250, 250))
        painter.drawEllipse(knob_x - 6, self.bar_y + self.bar_h // 2 - 6, 12, 12)
        painter.setBrush(QColor(40, 40, 40))
        painter.drawEllipse(knob_x - 3, self.bar_y + self.bar_h // 2 - 3, 6, 6)
        painter.setPen(QColor(30, 30, 30))
        txt_left = f"{visible}/{total} stitches"
        commands = self.viewer.command_events.get(visible, ())
        if commands:
            txt_left += f" | {' | '.join(commands)}"
        txt_center = f"{visible / total * 100:.1f}%"
        if self.viewer.bounds != (0, 0, 0, 0):
            bounds = self.viewer.bounds
            txt_right = (f"{bounds[2] - bounds[0]:.1f} x "
                         f"{bounds[3] - bounds[1]:.1f} mm | "
                         f"{self.viewer.color_count} color sections")
        else:
            txt_right = ""
        font_metrics = painter.fontMetrics()
        text_top = self.bar_y + self.bar_h + 3
        text_height = font_metrics.height()
        left_width = int(bar_width * 0.45)
        center_width = int(bar_width * 0.15)
        right_width = bar_width - left_width - center_width
        left_rect = QRect(bar_x, text_top, left_width, text_height)
        center_rect = QRect(bar_x + left_width, text_top,
                            center_width, text_height)
        right_rect = QRect(bar_x + left_width + center_width, text_top,
                           right_width, text_height)
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
