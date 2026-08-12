"""Qt preview images for the renderer picker."""

import numpy as np
from PySide6.QtGui import QColor, QImage, QPainter

from ..constants import DEFAULT_DARK_FACTOR, DEFAULT_LIGHT_FACTOR
from .registry import VECTOR_RENDERERS, render_stitches


def preview_stitches(renderer_key, width=360, height=220):
    """Render a small representative preview for the renderer picker."""
    center_x = width * 0.5
    center_y = height * 0.5
    inner_radius = min(width, height) * 0.14
    outer_radius = min(width, height) * 0.40
    angles = np.linspace(0.0, 2.0 * np.pi, 8, endpoint=False)
    colors = np.array(
        [
            (220, 55, 65),
            (225, 145, 35),
            (70, 150, 85),
            (35, 125, 210),
            (120, 75, 180),
            (210, 55, 145),
            (35, 160, 165),
            (190, 95, 45),
        ],
        dtype=np.float32,
    )
    stitches = np.empty((len(angles), 7), dtype=np.float32)
    for index, angle in enumerate(angles):
        direction_x = np.cos(angle)
        direction_y = np.sin(angle)
        stitches[index] = (
            center_x + direction_x * inner_radius,
            center_y + direction_y * inner_radius,
            center_x + direction_x * outer_radius,
            center_y + direction_y * outer_radius,
            *colors[index],
        )
    line_width = min(width, height) * 0.035
    if renderer_key in VECTOR_RENDERERS:
        image = QImage(width, height, QImage.Format_RGB888)
        image.fill(QColor(255, 255, 255))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)
        VECTOR_RENDERERS[renderer_key](
            painter, stitches, len(stitches), 1.0, 0, 0, line_width
        )
        painter.end()
        return image

    buffer = np.full((height, width, 3), 255, dtype=np.uint8)
    render_stitches(
        renderer_key,
        buffer,
        stitches,
        len(stitches),
        1.0,
        0,
        0,
        line_width,
        DEFAULT_DARK_FACTOR,
        DEFAULT_LIGHT_FACTOR,
    )
    return QImage(
        buffer.data,
        width,
        height,
        3 * width,
        QImage.Format_RGB888,
    ).copy()
