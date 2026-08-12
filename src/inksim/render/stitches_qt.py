"""Qt-backed stitch rendering helpers."""

import numpy as np
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
    visible_stitches = stitches[:visible_count]
    endpoints = visible_stitches[:, :4].copy()
    endpoints[:, 0::2] = endpoints[:, 0::2] * zoom + pan_x
    endpoints[:, 1::2] = endpoints[:, 1::2] * zoom + pan_y
    colors = visible_stitches[:, 4:7].astype(np.uint8)
    color_changes = np.any(colors[1:] != colors[:-1], axis=1)
    run_starts = np.concatenate(([0], np.flatnonzero(color_changes) + 1))
    run_ends = np.concatenate((run_starts[1:], [len(colors)]))

    for start, end in zip(run_starts, run_ends):
        color = colors[start]
        pen.setColor(QColor(int(color[0]), int(color[1]), int(color[2])))
        painter.setPen(pen)
        group = endpoints[start:end]
        painter.drawLines(
            [QLineF(x1, y1, x2, y2) for x1, y1, x2, y2 in group]
        )
