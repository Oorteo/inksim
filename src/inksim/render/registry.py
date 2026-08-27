"""Registered stitch renderers used by the viewer and renderer picker."""

from collections.abc import Callable
from dataclasses import dataclass

from .stitches import (
    render_realistic_kajiya_numba,
    render_realistic_numba,
    render_realistic_twist_numba,
    render_shaded_numba,
    render_shaded_volume_natural_numba,
    render_shaded_volume_numba,
)
from .stitches_gb import render_trueview_numba
from .stitches_qt import render_simple_qt
from .vintage_qt import render_vintage_qt


@dataclass(frozen=True)
class StitchRenderer:
    """Description and implementation of one stitch rendering mode."""

    key: str
    label: str
    kind: str
    render: Callable | None


STITCH_RENDERERS = (
    StitchRenderer("simple", "Simple", "vector", None),
    StitchRenderer("vintage", "Vintage", "vector", render_vintage_qt),
    StitchRenderer("shaded", "Shaded", "raster", render_shaded_numba),
    StitchRenderer("shaded_volume", "Shaded Volume", "raster", render_shaded_volume_numba),
    StitchRenderer("shaded_volume_natural", "Shaded Volume Natural", "raster", render_shaded_volume_natural_numba),
    StitchRenderer("realistic", "Realistic", "raster", render_realistic_numba),
    StitchRenderer("realistic_twist", "Realistic Twist", "raster", render_realistic_twist_numba),
    StitchRenderer("realistic_kajiya", "Realistic Kajiya", "raster", render_realistic_kajiya_numba),
    StitchRenderer("trueview", "TrueView (Wilcom-like)", "raster", render_trueview_numba),
)

RENDERERS_BY_KEY = {renderer.key: renderer for renderer in STITCH_RENDERERS}
VECTOR_RENDERERS = {
    "simple": render_simple_qt,
    "vintage": render_vintage_qt,
}


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
    show_stitches=True,
):
    """Render stitches using a registered renderer."""
    renderer = RENDERERS_BY_KEY[renderer_key]
    if renderer.kind != "raster" or renderer.render is None:
        raise ValueError(f"renderer is not raster-based: {renderer_key}")
    if not show_stitches or visible_count == 0:
        return
    if renderer_key in (
        "realistic",
        "realistic_twist",
        "realistic_kajiya",
        "shaded_volume",
        "shaded_volume_natural",
        "trueview",
    ):
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
