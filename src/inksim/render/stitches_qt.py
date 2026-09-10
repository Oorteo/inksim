# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Qt-backed stitch rendering helpers."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QLineF, Qt
from PySide6.QtGui import QColor, QPainter, QPen


def render_simple_qt(
    painter: QPainter,
    stitches: np.ndarray,
    visible_count: int,
    zoom: float,
    pan_x: float,
    pan_y: float,
    line_width: float,
    dark_factor: float = 0.0,
    light_factor: float = 0.0,
    show_stitches: bool = True,
) -> None:
    """Draw flat-color stitches with Qt's raster painter (fast, no AA)."""
    if not show_stitches or visible_count == 0:
        return
    # Ensure antialiasing is off for the fast simple renderer; round caps
    # and AA turn every stitch into an expensive vector shape operation.
    painter.setRenderHint(QPainter.Antialiasing, False)
    pen = QPen()
    # Keep the Qt simple renderer fast: cap the visual stroke width so huge
    # zoom/line_width combinations do not turn every stitch into an expensive
    # wide antialiased fill.  Physical 1:1 width is preserved up to the cap.
    pen.setWidthF(max(1.0, min(6.0, line_width * zoom)))
    # Round caps look better; with AA off the cost is acceptable.
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

    for start, end in zip(run_starts, run_ends, strict=False):
        color = colors[start]
        pen.setColor(QColor(int(color[0]), int(color[1]), int(color[2])))
        painter.setPen(pen)
        group = endpoints[start:end]
        painter.drawLines([QLineF(x1, y1, x2, y2) for x1, y1, x2, y2 in group])
