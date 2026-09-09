# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Rendering helpers used by the InkSim user interface."""

from __future__ import annotations

from .density import (
    calculate_stitch_density_numba as calculate_stitch_density_numba,
    render_density_numba as render_density_numba,
)
from .export import render_export_image as render_export_image
from .fabric import render_fabric_numba as render_fabric_numba
from .grid import render_grid_numba as render_grid_numba
from .previews import preview_stitches as preview_stitches
from .registry import (
    RENDERERS_BY_KEY as RENDERERS_BY_KEY,
    STITCH_RENDERERS as STITCH_RENDERERS,
    VECTOR_RENDERERS as VECTOR_RENDERERS,
    render_stitches as render_stitches,
)
from .stitches import (
    render_realistic_twist_numba as render_realistic_twist_numba,
    render_shaded_numba as render_shaded_numba,
    render_shaded_volume_natural_numba as render_shaded_volume_natural_numba,
    render_shaded_volume_numba as render_shaded_volume_numba,
)
from .stitches_gl import render_gpu_textured as render_gpu_textured
from .stitches_qt import render_simple_qt as render_simple_qt
from .viewport import render_viewport_raster as render_viewport_raster
