"""Registered stitch renderers used by the viewer and renderer picker."""

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from PySide6.QtGui import QColor, QImage, QPainter

from .stitches import (
    render_realistic_numba,
    render_shaded_numba,
)
from .stitches_qt import render_simple_qt


@dataclass(frozen=True)
class StitchRenderer:
    """Description and implementation of one stitch rendering mode."""

    key: str
    label: str
    kind: str
    render: Callable | None


STITCH_RENDERERS = (
    StitchRenderer("simple", "Simple", "vector", None),
    StitchRenderer("shaded", "Shaded", "raster", render_shaded_numba),
    StitchRenderer("realistic", "Realistic", "raster", render_realistic_numba),
)

RENDERERS_BY_KEY = {renderer.key: renderer for renderer in STITCH_RENDERERS}


def render_stitches(
    renderer_key,
    buffer,
    stitches,
    visible_count,
    zoom,
    pan_x,
    pan_y,
    line_width,
    dark_factor,
    light_factor,
):
    """Render stitches using a registered renderer."""
    renderer = RENDERERS_BY_KEY[renderer_key]
    if renderer.kind != "raster" or renderer.render is None:
        raise ValueError(f"renderer is not raster-based: {renderer_key}")
    if renderer_key == "realistic":
        renderer.render(
            buffer,
            stitches,
            visible_count,
            zoom,
            pan_x,
            pan_y,
            line_width,
            dark_factor,
            light_factor,
        )
    else:
        renderer.render(
            buffer,
            stitches,
            visible_count,
            zoom,
            pan_x,
            pan_y,
            zoom > 1.2,
            line_width,
            dark_factor,
            light_factor,
        )


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
    if renderer_key == "simple":
        image = QImage(width, height, QImage.Format_RGB888)
        image.fill(QColor(255, 255, 255))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)
        render_simple_qt(painter, stitches, len(stitches), 1.0, 0, 0, 0.55)
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
