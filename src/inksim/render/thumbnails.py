# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Sidecar thumbnails for embroidery designs.

A thumbnail lives next to its source file and keeps the full source name, so
``design.pes`` gets ``design.pes.png``. Every format of the same design keeps
its own image, the file manager shows them together, and a glob such as
``*.pes.png`` finds all thumbnails of one format.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pystitch as emb
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

from ..constants import AUTO_THREAD_COLORS, DEFAULT_LINE_WIDTH_MM
from ..formats import command_name, is_stitchblock_svg, read_embroidery_file
from .export import render_export_image

THUMBNAIL_SIZE = 256
THUMBNAIL_FORMAT = "PNG"
THUMBNAIL_RENDERER = "simple"


@dataclass(frozen=True)
class DesignPreview:
    """Render-ready stitch segments and the metadata the open dialog shows."""

    stitches: np.ndarray
    bounds: tuple[float, float, float, float]
    thread_colors: int


def thumbnail_path(source: Path) -> Path:
    """Return the sidecar thumbnail path for *source* (``design.pes.png``)."""
    return source.with_name(f"{source.name}.png")


def thumbnail_is_current(source: Path) -> bool:
    """Return whether *source* already has a thumbnail that is not older than it."""
    thumbnail = thumbnail_path(source)
    try:
        return thumbnail.stat().st_mtime >= source.stat().st_mtime
    except OSError:
        return False


def _thread_rgb(thread: Any, color_index: int) -> tuple[int, int, int]:
    if hasattr(thread, "get_red"):
        return (
            int(thread.get_red()),
            int(thread.get_green()),
            int(thread.get_blue()),
        )
    if isinstance(thread, (list, tuple)):
        return (int(thread[0]), int(thread[1]), int(thread[2]))
    return AUTO_THREAD_COLORS[color_index % len(AUTO_THREAD_COLORS)]


def build_design_preview(pattern: Any) -> DesignPreview:
    """Turn a PyStitch pattern into render-ready stitch segments.

    This mirrors the segment building in the viewer, so a thumbnail looks like
    the preview pane: a stitch becomes a segment from the previous point to the
    next one, a jump moves the needle, and a colour change switches the thread.
    """
    threadlist = getattr(pattern, "threadlist", None) or ()
    has_thread_colors = bool(threadlist)
    palette: Any = threadlist if has_thread_colors else AUTO_THREAD_COLORS
    segments: list[tuple[float, float, float, float, int, int, int]] = []
    last_x = last_y = 0.0
    color_index = 0
    min_x = min_y = 1e9
    max_x = max_y = -1e9

    for stitch in pattern.stitches:
        x = stitch[0] / 10.0
        y = stitch[1] / 10.0
        raw_command = stitch[2] if len(stitch) > 2 else emb.STITCH
        if hasattr(emb, "decode_embroidery_command"):
            cmd, _thread, _needle, _order = emb.decode_embroidery_command(raw_command)
        else:
            cmd = raw_command
        if hasattr(emb, "JUMP") and cmd == emb.JUMP:
            last_x, last_y = x, y
            continue
        if hasattr(emb, "END") and cmd == emb.END:
            break
        if hasattr(emb, "COLOR_CHANGE") and cmd == emb.COLOR_CHANGE:
            color_index += 1
            last_x, last_y = x, y
            continue
        name = command_name(cmd)
        if name is not None and name != "STITCH":
            continue
        if has_thread_colors:
            thread = palette[min(color_index, len(palette) - 1)]
        else:
            thread = AUTO_THREAD_COLORS[color_index % len(AUTO_THREAD_COLORS)]
        red, green, blue = _thread_rgb(thread, color_index)
        segments.append((last_x, last_y, x, y, red, green, blue))
        min_x = min(min_x, last_x, x)
        min_y = min(min_y, last_y, y)
        max_x = max(max_x, last_x, x)
        max_y = max(max_y, last_y, y)
        last_x, last_y = x, y

    if not segments:
        return DesignPreview(np.zeros((0, 7), dtype=np.float32), (0.0, 0.0, 0.0, 0.0), 0)
    return DesignPreview(
        np.array(segments, dtype=np.float32),
        (min_x, min_y, max_x, max_y),
        len(threadlist),
    )


def load_design_preview(source: Path) -> DesignPreview | None:
    """Read *source* and return its render-ready preview, or None when unreadable."""
    try:
        pattern = read_embroidery_file(source)
    except Exception:
        return None
    if pattern is None:
        return None
    preview = build_design_preview(pattern)
    return preview if preview.stitches.shape[0] else None


def render_thumbnail(source: Path, size: int = THUMBNAIL_SIZE) -> QImage | None:
    """Render a square thumbnail image for *source*, or None when it cannot be read."""
    preview = load_design_preview(source)
    if preview is None:
        return None
    return render_export_image(
        preview.stitches,
        preview.bounds,
        size,
        size,
        DEFAULT_LINE_WIDTH_MM,
        THUMBNAIL_RENDERER,
        dpi=96,
        background="transparent",
    )


def render_svg_thumbnail(source: Path, size: int = THUMBNAIL_SIZE) -> QImage | None:
    """Rasterise a plain SVG with Qt, for documents that are not stitch files."""
    renderer = QSvgRenderer(str(source))
    if not renderer.isValid():
        return None
    image = QImage(size, size, QImage.Format_RGBA8888)
    image.fill(Qt.GlobalColor.transparent)
    box = renderer.viewBoxF()
    if box.width() <= 0 or box.height() <= 0:
        fallback = renderer.defaultSize()
        box = QRectF(0, 0, fallback.width(), fallback.height())
    if box.width() <= 0 or box.height() <= 0:
        return None
    margin = max(12.0, size * 0.06)
    available = size - 2 * margin
    scale = min(available / box.width(), available / box.height())
    width = box.width() * scale
    height = box.height() * scale
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(
        painter,
        QRectF((size - width) / 2, (size - height) / 2, width, height),
    )
    painter.end()
    return image


def render_source_thumbnail(source: Path, size: int = THUMBNAIL_SIZE) -> QImage | None:
    """Render *source* as a thumbnail, using stitches only for real stitch files."""
    if source.suffix.lower() == ".svg" and not is_stitchblock_svg(source):
        return render_svg_thumbnail(source, size)
    return render_thumbnail(source, size)


def write_thumbnail(
    source: Path,
    *,
    size: int = THUMBNAIL_SIZE,
    overwrite: bool = False,
) -> Path | None:
    """Write the sidecar thumbnail for *source* and return its path."""
    thumbnail = thumbnail_path(source)
    if thumbnail_is_current(source) and not overwrite:
        return thumbnail
    image = render_source_thumbnail(source, size)
    if image is None:
        return None
    # PySide6 accepts the format name; its stubs only describe the bytes overload.
    if not image.save(str(thumbnail), THUMBNAIL_FORMAT):  # type: ignore[call-overload]
        return None
    return thumbnail
