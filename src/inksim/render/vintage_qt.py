"""Vector capsule renderer inspired by the historical Qt stitch view."""

from PySide6.QtCore import QLineF, QPointF, Qt
from PySide6.QtGui import QBrush, QColor, QGradient, QLinearGradient, QPainterPath


def render_vintage_qt(
    painter,
    stitches,
    visible_count,
    zoom,
    pan_x,
    pan_y,
    line_width,
    show_stitches=True,
):
    """Draw stitches as filled, shaded thread capsules in Qt."""
    if not show_stitches or visible_count == 0:
        return

    half_width = max(0.6, line_width * zoom * 0.5)
    cap = half_width * 0.5522847
    painter.setPen(Qt.NoPen)
    for stitch in stitches[:visible_count]:
        start = QPointF(stitch[0] * zoom + pan_x, stitch[1] * zoom + pan_y)
        end = QPointF(stitch[2] * zoom + pan_x, stitch[3] * zoom + pan_y)
        line = QLineF(start, end)
        length = line.length()
        if length <= 0.01:
            continue

        tangent_x = (end.x() - start.x()) / length
        tangent_y = (end.y() - start.y()) / length
        normal_x = -tangent_y
        normal_y = tangent_x
        side = QPointF(normal_x * half_width, normal_y * half_width)
        start_left = start - side
        start_right = start + side
        end_left = end - side
        end_right = end + side
        end_round = QPointF(tangent_x * cap, tangent_y * cap)
        start_round = QPointF(tangent_x * cap, tangent_y * cap)

        path = QPainterPath()
        path.moveTo(start_left)
        path.lineTo(end_left)
        path.cubicTo(
            end_left + end_round,
            end_right + end_round,
            end_right,
        )
        path.lineTo(start_right)
        path.cubicTo(
            start_right - start_round,
            start_left - start_round,
            start_left,
        )
        path.closeSubpath()

        base = QColor(int(stitch[4]), int(stitch[5]), int(stitch[6]))
        dark = base.darker(120)
        hue, saturation, lightness, alpha = base.getHsl()
        light = QColor.fromHsl(
            hue,
            saturation,
            min(255, lightness + 70),
            alpha,
        )
        gradient_start = QPointF(
            start.x() + tangent_x * length * 0.1,
            start.y() + tangent_y * length * 0.1,
        )
        gradient_end = QPointF(
            start.x() + tangent_x * length * 0.5,
            start.y() + tangent_y * length * 0.5,
        )
        gradient = QLinearGradient(gradient_start, gradient_end)
        gradient.setSpread(QGradient.ReflectSpread)
        gradient.setColorAt(0.0, dark)
        gradient.setColorAt(0.5, light)
        painter.fillPath(path, QBrush(gradient))
