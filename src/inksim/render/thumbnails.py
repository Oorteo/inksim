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
from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QImage, QImageReader, QPainter
from PySide6.QtSvg import QSvgRenderer

from ..constants import AUTO_THREAD_COLORS, DEFAULT_LINE_WIDTH_MM
from ..formats import command_name, is_stitchblock_svg, read_embroidery_file
from .export import render_export_image

THUMBNAIL_SIZE = 256
THUMBNAIL_FORMAT = "PNG"
THUMBNAIL_RENDERER = "simple"
# SVG renders are supersampled before scaling down; a higher factor renders
# smoother edges and, because the gradients stay regular, smaller PNG files.
SVG_SUPERSAMPLE = 12
SVG_RENDER_LIMIT = 3072

# Bump the version when the thumbnail pipeline changes in a way that should
# invalidate existing files, so "update" regenerates them without a full run.
STAMP_KEY = "InkSimThumbnail"
DETAILS_KEY = "InkSimDesign"
STAMP_VERSION = 1


@dataclass(frozen=True)
class ThumbnailDetails:
    """Design facts recorded next to the thumbnail, so lists do not re-read files."""

    stitches: int
    colors: int
    width_mm: float
    height_mm: float

    def encode(self) -> str:
        return (
            f"stitches={self.stitches};colors={self.colors}"
            f";width_mm={self.width_mm:.3f};height_mm={self.height_mm:.3f}"
        )

    @classmethod
    def decode(cls, text: str | None) -> ThumbnailDetails | None:
        if not text:
            return None
        values = dict(part.split("=", 1) for part in text.split(";") if "=" in part)
        try:
            return cls(
                stitches=int(values["stitches"]),
                colors=int(values["colors"]),
                width_mm=float(values["width_mm"]),
                height_mm=float(values["height_mm"]),
            )
        except (KeyError, ValueError):
            return None


def thumbnail_details(source: Path) -> ThumbnailDetails | None:
    """Return the design facts stored with the thumbnail of *source*, if any."""
    reader = QImageReader(str(thumbnail_path(source)))
    return ThumbnailDetails.decode(reader.text(DETAILS_KEY))


def thumbnail_stamp(size: int = THUMBNAIL_SIZE) -> str:
    """Return the parameters recorded inside every thumbnail we write."""
    return f"version={STAMP_VERSION};size={size};renderer={THUMBNAIL_RENDERER}"


@dataclass(frozen=True)
class DesignPreview:
    """Render-ready stitch segments and the metadata the open dialog shows."""

    stitches: np.ndarray
    bounds: tuple[float, float, float, float]
    thread_colors: int


def thumbnail_path(source: Path) -> Path:
    """Return the sidecar thumbnail path for *source* (``design.pes.png``)."""
    return source.with_name(f"{source.name}.png")


def thumbnail_is_current(source: Path, size: int = THUMBNAIL_SIZE) -> bool:
    """Return whether *source* has a thumbnail made with the current settings.

    The image is up to date when it is not older than the source and carries
    the parameters InkSim writes today, so changed render settings invalidate
    it even though the file itself did not move.
    """
    thumbnail = thumbnail_path(source)
    try:
        if thumbnail.stat().st_mtime < source.stat().st_mtime:
            return False
    except OSError:
        return False
    return QImageReader(str(thumbnail)).text(STAMP_KEY) == thumbnail_stamp(size)


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


def render_preview_thumbnail(preview: DesignPreview, size: int = THUMBNAIL_SIZE) -> QImage:
    """Render a loaded design as a square thumbnail image."""
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


def render_thumbnail(source: Path, size: int = THUMBNAIL_SIZE) -> QImage | None:
    """Render a square thumbnail image for *source*, or None when it cannot be read."""
    preview = load_design_preview(source)
    if preview is None:
        return None
    return render_preview_thumbnail(preview, size)


def _drawn_area(image: QImage) -> QRect | None:
    """Return the bounding box of the visible pixels, or None for a blank image."""
    width = image.width()
    height = image.height()
    stride = image.bytesPerLine()
    raw = np.frombuffer(image.constBits(), dtype=np.uint8, count=stride * height)
    alpha = raw.reshape(height, stride)[:, : width * 4].reshape(height, width, 4)[:, :, 3]
    rows = np.flatnonzero(alpha.any(axis=1))
    columns = np.flatnonzero(alpha.any(axis=0))
    if rows.size == 0 or columns.size == 0:
        return None
    return QRect(
        int(columns[0]),
        int(rows[0]),
        int(columns[-1] - columns[0] + 1),
        int(rows[-1] - rows[0] + 1),
    )


def render_svg_thumbnail(source: Path, size: int = THUMBNAIL_SIZE) -> QImage | None:
    """Rasterise a plain SVG with Qt, for documents that are not stitch files.

    Documents often use a page much larger than the drawing itself, so the
    render is cropped to the visible pixels before it is scaled into the
    square canvas; otherwise the artwork ends up as a speck in empty space.
    """
    renderer = QSvgRenderer(str(source))
    if not renderer.isValid():
        return None
    render_size = min(max(size * SVG_SUPERSAMPLE, 512), SVG_RENDER_LIMIT)
    render = QImage(render_size, render_size, QImage.Format_RGBA8888)
    render.fill(Qt.GlobalColor.transparent)
    box = renderer.viewBoxF()
    if box.width() <= 0 or box.height() <= 0:
        fallback = renderer.defaultSize()
        box = QRectF(0, 0, fallback.width(), fallback.height())
    if box.width() <= 0 or box.height() <= 0:
        return None
    scale = min(render_size / box.width(), render_size / box.height())
    width = box.width() * scale
    height = box.height() * scale
    painter = QPainter(render)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(
        painter,
        QRectF((render_size - width) / 2, (render_size - height) / 2, width, height),
    )
    painter.end()

    drawn = _drawn_area(render)
    if drawn is None:
        return None
    margin = max(12.0, size * 0.06)
    available = size - 2 * margin
    fit = min(available / drawn.width(), available / drawn.height())
    target_width = drawn.width() * fit
    target_height = drawn.height() * fit
    image = QImage(size, size, QImage.Format_RGBA8888)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.drawImage(
        QRectF(
            (size - target_width) / 2,
            (size - target_height) / 2,
            target_width,
            target_height,
        ),
        render,
        QRectF(drawn),
    )
    painter.end()
    return image


def render_source_thumbnail(source: Path, size: int = THUMBNAIL_SIZE) -> QImage | None:
    """Render *source* as a thumbnail, using stitches only for real stitch files."""
    if source.suffix.lower() == ".svg" and not is_stitchblock_svg(source):
        return render_svg_thumbnail(source, size)
    return render_thumbnail(source, size)


def _render_with_details(source: Path, size: int) -> tuple[QImage | None, ThumbnailDetails | None]:
    """Render a thumbnail and collect the design facts worth caching beside it."""
    if source.suffix.lower() == ".svg" and not is_stitchblock_svg(source):
        return render_svg_thumbnail(source, size), None
    preview = load_design_preview(source)
    if preview is None:
        return None, None
    min_x, min_y, max_x, max_y = preview.bounds
    return (
        render_preview_thumbnail(preview, size),
        ThumbnailDetails(
            stitches=int(preview.stitches.shape[0]),
            colors=preview.thread_colors,
            width_mm=float(max_x - min_x),
            height_mm=float(max_y - min_y),
        ),
    )


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
    image, details = _render_with_details(source, size)
    if image is None:
        return None
    image.setText(STAMP_KEY, thumbnail_stamp(size))
    if details is not None:
        image.setText(DETAILS_KEY, details.encode())
    # PySide6 accepts the format name; its stubs only describe the bytes overload.
    if not image.save(str(thumbnail), THUMBNAIL_FORMAT):  # type: ignore[call-overload]
        return None
    return thumbnail
