# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Raster composition for the embroidery viewport."""

from __future__ import annotations

import numpy as np

from .density import render_density_numba
from .fabric import render_fabric_numba
from .grid import render_grid_numba
from .registry import VECTOR_RENDERERS, render_stitches


def render_viewport_raster(
    buffer: np.ndarray,
    active_renderer: str,
    stitches: np.ndarray,
    visible_count: int,
    stitch_points: np.ndarray,
    stitch_density: np.ndarray,
    repeated_stitch: np.ndarray,
    zoom: float,
    pan_x: float,
    pan_y: float,
    line_width: float,
    dark_factor: float,
    light_factor: float,
    show_grid: bool,
    show_density: bool,
    show_stitches: bool = True,
    lighting_mode: str = "rich",
) -> None:
    """Compose the non-Qt viewport layers into an RGB buffer."""
    # Fabric background is GPU-only for now; the CPU realistic_twist renderer
    # is too slow when it also has to synthesize fabric behind the stitches.
    if active_renderer in ("realistic_twist",) and zoom > 1.2 and False:
        render_fabric_numba(buffer, zoom)
    if show_grid:
        render_grid_numba(buffer, zoom, pan_x, pan_y)
    if active_renderer not in VECTOR_RENDERERS and stitches.shape[0] > 0 and visible_count > 0:
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
            lighting_mode,
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
