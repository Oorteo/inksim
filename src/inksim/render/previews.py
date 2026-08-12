"""Qt preview images for the renderer picker."""

import numpy as np
from PySide6.QtGui import QColor, QImage, QPainter

from .registry import VECTOR_RENDERERS, render_stitches


def preview_stitches(renderer_key, width=360, height=220):
    """Render a small representative preview for the renderer picker."""
    stitches = np.array(
        [
            (35, 45, 145, 150, 220, 55, 65),
            (145, 150, 255, 55, 65, 150, 210),
            (255, 55, 325, 160, 55, 180, 95),
        ],
        dtype=np.float32,
    )
    if renderer_key in VECTOR_RENDERERS:
        image = QImage(width, height, QImage.Format_RGB888)
        image.fill(QColor(255, 255, 255))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)
        VECTOR_RENDERERS[renderer_key](
            painter, stitches, len(stitches), 1.0, 0, 0, 0.55
        )
        painter.end()
        return image

    buffer = np.full((height, width, 3), 255, dtype=np.uint8)
    render_stitches(
        renderer_key, buffer, stitches, len(stitches), 1.0, 0, 0, 0.55, 0.75, 0.45
    )
    return QImage(
        buffer.data,
        width,
        height,
        3 * width,
        QImage.Format_RGB888,
    ).copy()
