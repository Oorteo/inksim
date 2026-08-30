"""Raster composition for the embroidery viewport."""

from .density import render_density_numba
from .fabric import render_fabric_numba
from .grid import render_grid_numba
from .registry import VECTOR_RENDERERS, render_stitches


def render_viewport_raster(
    buffer,
    active_renderer,
    stitches,
    visible_count,
    stitch_points,
    stitch_density,
    repeated_stitch,
    zoom,
    pan_x,
    pan_y,
    line_width,
    dark_factor,
    light_factor,
    show_grid,
    show_density,
    show_stitches=True,
):
    """Compose the non-Qt viewport layers into an RGB buffer."""
    if active_renderer in ("realistic_twist",) and zoom > 1.2:
        render_fabric_numba(buffer, zoom)
    if show_grid:
        render_grid_numba(buffer, zoom, pan_x, pan_y)
    if (
        active_renderer not in VECTOR_RENDERERS
        and stitches.shape[0] > 0
        and visible_count > 0
    ):
        render_stitches(
            active_renderer,
            buffer,
            stitches,
            visible_count,
            zoom,
            pan_x,
            pan_y,
            line_width,
            dark_factor,
            light_factor,
            show_stitches,
        )
    if show_density and len(stitch_points) > 0:
        render_density_numba(
            buffer,
            stitch_points,
            stitch_density,
            repeated_stitch,
            visible_count,
            zoom,
            pan_x,
            pan_y,
        )
