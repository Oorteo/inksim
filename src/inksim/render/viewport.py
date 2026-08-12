"""Raster composition for the embroidery viewport."""

from .density import render_density_numba
from .fabric import render_fabric_numba
from .grid import render_grid_numba
from .registry import render_stitches


def render_viewport_raster(
    buffer,
    active_renderer,
    stitches,
    visible_count,
    stitch_points,
    stitch_density,
    zoom,
    pan_x,
    pan_y,
    line_width,
    dark_factor,
    light_factor,
    show_grid,
    show_density,
):
    """Compose the non-Qt viewport layers into an RGB buffer."""
    if active_renderer == "realistic" and zoom > 1.2:
        render_fabric_numba(buffer, zoom)
    if show_grid:
        render_grid_numba(buffer, zoom, pan_x, pan_y)
    if (
        active_renderer != "simple"
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
        )
    if show_density and len(stitch_points) > 0:
        render_density_numba(
            buffer,
            stitch_points,
            stitch_density,
            visible_count,
            zoom,
            pan_x,
            pan_y,
        )
