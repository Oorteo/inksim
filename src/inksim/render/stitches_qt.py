"""Qt-backed stitch rendering helpers."""

from PySide6.QtCore import QLineF, Qt
from PySide6.QtGui import QColor, QPainter, QPen


def render_simple_qt(
    painter,
    stitches,
    visible_count,
    zoom,
    pan_x,
    pan_y,
    line_width,
    show_stitches=True,
):
    """Draw flat-color stitches with Qt's antialiased vector painter."""
    if not show_stitches or visible_count == 0:
        return
    pen = QPen()
    pen.setWidthF(max(1.0, line_width * zoom))
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    for stitch in stitches[:visible_count]:
        pen.setColor(QColor(int(stitch[4]), int(stitch[5]), int(stitch[6])))
        painter.setPen(pen)
        painter.drawLine(
            QLineF(
                stitch[0] * zoom + pan_x,
                stitch[1] * zoom + pan_y,
                stitch[2] * zoom + pan_x,
                stitch[3] * zoom + pan_y,
            )
        )
