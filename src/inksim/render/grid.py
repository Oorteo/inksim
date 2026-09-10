# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Grid rendering helpers."""

from __future__ import annotations

import numba
import numpy as np


@numba.njit(cache=True)
def _mix_channel(
    bg: int | np.uint8,
    line: int | np.uint8,
    k: int | np.uint8,
    denom: int | np.uint8,
) -> np.uint8:
    """Blend a single colour channel toward line with strength k/denom."""
    return np.uint8((int(bg) * (denom - k) + int(line) * k) // denom)


@numba.njit(cache=True)
def render_grid_numba(buf: np.ndarray, zoom: float, pan_x: float, pan_y: float) -> None:
    # Draw helper grid into the RGB buffer.
    # - every 1 mm: fine grid line at high zoom levels
    # - every 10 mm: minor grid line
    # - every 50 mm: major grid line
    # - x=0 / y=0: highlighted axes
    # zoom converts mm -> pixels, pan is screen-space origin offset.
    #
    # Colours are blended with the background so the grid looks subtle,
    # matching the GPU shader (fine ~15%, minor ~18%, major ~30%, axes ~50%).
    h, w, _ = buf.shape
    show_fine_grid = zoom >= 8.0
    solid_fine_grid = zoom >= 14.0
    fine_grid_dot_step = 2 if zoom >= 11.0 else 4
    solid_centimeter_grid = zoom >= 2.5
    # 0.1 mm micro grid is disabled in CPU mode: it is far too expensive to
    # draw on the host while the GPU shader can do it in parallel.  Leave the
    # fade calculation here so the GPU path can still mirror it if desired.
    micro_fade = 0.0
    if zoom >= 30.0:
        micro_fade = min(1.0, (zoom - 30.0) / 20.0)
    show_micro_grid = False

    # Choose light or dark grid lines based on the background colour.
    bg_lum = (int(buf[0, 0, 0]) + int(buf[0, 0, 1]) + int(buf[0, 0, 2])) // 3
    if bg_lum > 127:
        line = 0  # dark lines on light background
    else:
        line = 255  # light lines on dark background

    # World-space area currently visible in the viewport.
    x_world_min = (-pan_x) / zoom
    x_world_max = (w - pan_x) / zoom
    y_world_min = (-pan_y) / zoom
    y_world_max = (h - pan_y) / zoom

    # Snap bounds to full 10 mm steps so edge lines are still drawn.
    x_start = int(np.floor(x_world_min / 10.0) * 10)
    x_end = int(np.ceil(x_world_max / 10.0) * 10)
    y_start = int(np.floor(y_world_min / 10.0) * 10)
    y_end = int(np.ceil(y_world_max / 10.0) * 10)

    # Blend denominators keep the grid subtle, matching the GL shader.
    denom = np.uint8(100)

    if show_fine_grid:
        x_fine_start = int(np.floor(x_world_min))
        x_fine_end = int(np.ceil(x_world_max))
        y_fine_start = int(np.floor(y_world_min))
        y_fine_end = int(np.ceil(y_world_max))

        for xw in range(x_fine_start, x_fine_end + 1):
            if xw % 10 == 0:
                continue
            sx = int(xw * zoom + pan_x)
            if sx < 0 or sx >= w:
                continue
            for y in range(h):
                if not solid_fine_grid and y % fine_grid_dot_step != 0:
                    continue
                buf[y, sx, 0] = _mix_channel(buf[y, sx, 0], line, 15, denom)
                buf[y, sx, 1] = _mix_channel(buf[y, sx, 1], line, 15, denom)
                buf[y, sx, 2] = _mix_channel(buf[y, sx, 2], line, 15, denom)

        for yw in range(y_fine_start, y_fine_end + 1):
            if yw % 10 == 0:
                continue
            sy = int(yw * zoom + pan_y)
            if sy < 0 or sy >= h:
                continue
            for x in range(w):
                if not solid_fine_grid and x % fine_grid_dot_step != 0:
                    continue
                buf[sy, x, 0] = _mix_channel(buf[sy, x, 0], line, 15, denom)
                buf[sy, x, 1] = _mix_channel(buf[sy, x, 1], line, 15, denom)
                buf[sy, x, 2] = _mix_channel(buf[sy, x, 2], line, 15, denom)

    # 0.1 mm micro grid (fades in at high zoom, matching the GPU shader).
    if show_micro_grid:
        micro_strength = int(round(10 * micro_fade))
        x_micro_start = int(np.floor(x_world_min / 0.1))
        x_micro_end = int(np.ceil(x_world_max / 0.1))
        y_micro_start = int(np.floor(y_world_min / 0.1))
        y_micro_end = int(np.ceil(y_world_max / 0.1))

        for xm in range(x_micro_start, x_micro_end + 1):
            xw_micro = xm * 0.1
            if abs(xw_micro - round(xw_micro)) < 1e-6:
                continue  # skip 1 mm lines (already drawn by the fine grid)
            sx = int(xw_micro * zoom + pan_x)
            if sx < 0 or sx >= w:
                continue
            for y in range(h):
                buf[y, sx, 0] = _mix_channel(buf[y, sx, 0], line, micro_strength, denom)
                buf[y, sx, 1] = _mix_channel(buf[y, sx, 1], line, micro_strength, denom)
                buf[y, sx, 2] = _mix_channel(buf[y, sx, 2], line, micro_strength, denom)

        for ym in range(y_micro_start, y_micro_end + 1):
            yw_micro = ym * 0.1
            if abs(yw_micro - round(yw_micro)) < 1e-6:
                continue
            sy = int(yw_micro * zoom + pan_y)
            if sy < 0 or sy >= h:
                continue
            for x in range(w):
                buf[sy, x, 0] = _mix_channel(buf[sy, x, 0], line, micro_strength, denom)
                buf[sy, x, 1] = _mix_channel(buf[sy, x, 1], line, micro_strength, denom)
                buf[sy, x, 2] = _mix_channel(buf[sy, x, 2], line, micro_strength, denom)

    # Vertical lines.
    for xw in range(x_start, x_end + 1, 10):
        # Project world x to screen x.
        sx = int(xw * zoom + pan_x)
        if sx < 0 or sx >= w:
            continue

        # Choose line style.
        is_major = xw % 50 == 0
        is_axis = xw == 0

        if is_axis:
            r, g, b = 200, 100, 100
            strength = 50
        elif is_major:
            r, g, b = line, line, line
            strength = 30
        elif solid_centimeter_grid:
            r, g, b = line, line, line
            strength = 18
        else:
            # At low zoom the lines are only a few pixels apart; drawing them
            # as dotted (every 3rd pixel) creates moiré patterns with the
            # screen pixel grid. Draw a continuous but fainter line instead.
            r, g, b = line, line, line
            strength = 9

        # Keep crowded grids subtle, but make centimeter lines continuous
        # once there is enough room between them.
        for y in range(h):
            if not (is_axis or solid_centimeter_grid) and y % 3 != 0:
                continue
            buf[y, sx, 0] = _mix_channel(buf[y, sx, 0], r, strength, denom)
            buf[y, sx, 1] = _mix_channel(buf[y, sx, 1], g, strength, denom)
            buf[y, sx, 2] = _mix_channel(buf[y, sx, 2], b, strength, denom)

    # Horizontal lines (same logic as vertical).
    for yw in range(y_start, y_end + 1, 10):
        sy = int(yw * zoom + pan_y)
        if sy < 0 or sy >= h:
            continue
        is_major = yw % 50 == 0
        is_axis = yw == 0

        if is_axis:
            r, g, b = 100, 200, 100
            strength = 50
        elif is_major:
            r, g, b = line, line, line
            strength = 30
        elif solid_centimeter_grid:
            r, g, b = line, line, line
            strength = 18
        else:
            # At low zoom the lines are only a few pixels apart; drawing them
            # as dotted (every 3rd pixel) creates moiré patterns with the
            # screen pixel grid. Draw a continuous but fainter line instead.
            r, g, b = line, line, line
            strength = 9

        for x in range(w):
            if not (is_axis or solid_centimeter_grid) and x % 3 != 0:
                continue
            buf[sy, x, 0] = _mix_channel(buf[sy, x, 0], r, strength, denom)
            buf[sy, x, 1] = _mix_channel(buf[sy, x, 1], g, strength, denom)
            buf[sy, x, 2] = _mix_channel(buf[sy, x, 2], b, strength, denom)
