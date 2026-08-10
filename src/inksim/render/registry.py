"""Registered stitch renderers used by the viewer and renderer picker."""

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from .stitches import render_realistic_numba, render_shaded_numba


@dataclass(frozen=True)
class StitchRenderer:
    """Description and implementation of one stitch rendering mode."""

    key: str
    label: str
    render: Callable


STITCH_RENDERERS = (
    StitchRenderer("shaded", "Shaded", render_shaded_numba),
    StitchRenderer("realistic", "Realistic", render_realistic_numba),
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
    buffer = np.full((height, width, 3), 255, dtype=np.uint8)
    stitches = np.array(
        [
            (35, 45, 145, 150, 220, 55, 65),
            (145, 150, 255, 55, 65, 150, 210),
            (255, 55, 325, 160, 55, 180, 95),
        ],
        dtype=np.float32,
    )
    render_stitches(
        renderer_key, buffer, stitches, len(stitches), 1.0, 0, 0, 0.55, 0.75, 0.45
    )
    return buffer
