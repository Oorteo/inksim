# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter

from .registry import RENDERERS_BY_KEY, VECTOR_RENDERERS
from .viewport import render_viewport_raster

def render_export_image(
    stitches,
    bounds,
    width,
    height,
    line_width,
    renderer_key,
    dpi=None,
    background="transparent",
    grid=False,
    dark_factor=0.75,
    light_factor=0.45,
    scale_factor=1.0,
):
    """Render a PNG/WebP/JPEG using the same renderer as the viewer."""
    if renderer_key not in RENDERERS_BY_KEY:
        raise ValueError(f"unknown renderer: {renderer_key}")

    min_x, min_y, max_x, max_y = bounds
    design_width = max(max_x - min_x, 1.0)
    design_height = max(max_y - min_y, 1.0)
    width = max(1, round(width * scale_factor))
    height = max(1, round(height * scale_factor))
    margin = max(12, min(width, height) * 0.06)
    zoom = min(
        (width - 2 * margin) / design_width,
        (height - 2 * margin) / design_height,
    )
    offset_x = (width - design_width * zoom) / 2 - min_x * zoom
    offset_y = (height - design_height * zoom) / 2 - min_y * zoom
    if isinstance(background, (tuple, list)) and len(background) == 3:
        base_color = tuple(int(c) for c in background)
        opaque = True
    elif background == "white":
        base_color = (255, 255, 255)
        opaque = True
    else:
        base_color = (1, 2, 3)
        opaque = False
    buffer = np.empty((height, width, 4), dtype=np.uint8)
    buffer[:, :, :3] = base_color
    buffer[:, :, 3] = 255 if opaque else 0
    render_viewport_raster(
        buffer,
        renderer_key,
        stitches,
        len(stitches),
        np.empty((0, 2), dtype=np.float32),
        np.empty((0, ), dtype=np.float32),
        np.empty((0, ), dtype=np.bool_),
        zoom,
        offset_x,
        offset_y,
        line_width,
        dark_factor,
        light_factor,
        grid,
        False,
        True,
    )
    if renderer_key not in VECTOR_RENDERERS and not opaque:
        changed = np.any(buffer[:, :, :3] != base_color, axis=2)
        buffer[:, :, 3] = np.where(changed, 255, 0)
    image = QImage(
        buffer.data,
        width,
        height,
        4 * width,
        QImage.Format_RGBA8888,
    ).copy()
    if renderer_key in VECTOR_RENDERERS:
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)
        VECTOR_RENDERERS[renderer_key](
            painter,
            stitches,
            len(stitches),
            zoom,
            offset_x,
            offset_y,
            line_width,
            dark_factor,
            light_factor,
            True,
        )
        painter.end()
    # Always set the standard physical-resolution tags (PNG pHYs / JPEG EXIF
    # resolution) so every image viewer/editor can recover the real-world size
    # from pixels-per-meter. When no explicit DPI is supplied, derive one from
    # the pixel size and the design dimensions.
    if dpi is None or dpi <= 0:
        dpi = max(1.0, min(width, height) / max(design_width, design_height) * 25.4)
    dots_per_meter = round(dpi / 0.0254)
    image.setDotsPerMeterX(dots_per_meter)
    image.setDotsPerMeterY(dots_per_meter)

    # One human-readable comment with the key facts. InkSim-specific tags are
    # secondary to the standard resolution tags above.
    image.setText("InkSim", (
        f"created_by=InkSim; "
        f"design_size_mm={design_width:.3f}x{design_height:.3f}; "
        f"dpi={dpi:.2f}; "
        f"renderer={renderer_key}; "
        f"background={background}"
    ))
    return image
