import numba
import numpy as np

@numba.njit(cache=True)
def render_grid_numba(buf, zoom, pan_x, pan_y):
    # Draw helper grid into the RGB buffer.
    # - every 1 mm: fine grid line at high zoom levels
    # - every 10 mm: minor grid line
    # - every 50 mm: major grid line
    # - x=0 / y=0: highlighted axes
    # zoom converts mm -> pixels, pan is screen-space origin offset.
    h, w, _ = buf.shape
    show_fine_grid = zoom >= 8.0
    solid_fine_grid = zoom >= 14.0
    fine_grid_dot_step = 2 if zoom >= 11.0 else 4
    fine_grid_color = 235 if zoom >= 14.0 else 242
    solid_centimeter_grid = zoom >= 2.5

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
                buf[y, sx, 0] = fine_grid_color
                buf[y, sx, 1] = fine_grid_color
                buf[y, sx, 2] = fine_grid_color

        for yw in range(y_fine_start, y_fine_end + 1):
            if yw % 10 == 0:
                continue
            sy = int(yw * zoom + pan_y)
            if sy < 0 or sy >= h:
                continue
            for x in range(w):
                if not solid_fine_grid and x % fine_grid_dot_step != 0:
                    continue
                buf[sy, x, 0] = fine_grid_color
                buf[sy, x, 1] = fine_grid_color
                buf[sy, x, 2] = fine_grid_color

    # Vertical lines.
    for xw in range(x_start, x_end+1, 10):
        # Project world x to screen x.
        sx = int(xw * zoom + pan_x)
        if sx < 0 or sx >= w: continue

        # Choose line style.
        is_major = (xw % 50 == 0)
        is_axis = (xw == 0)

        if is_axis: r,g,b = 200, 100, 100      # red axis
        elif is_major: r,g,b = 180, 180, 180   # major line
        else: r,g,b = 218, 218, 218            # minor line

        # Keep crowded grids subtle, but make centimeter lines continuous
        # once there is enough room between them.
        for y in range(h):
            if is_axis or solid_centimeter_grid:
                buf[y, sx, 0] = r
                buf[y, sx, 1] = g
                buf[y, sx, 2] = b
            else:
                if y % 3 != 0: continue
                buf[y, sx, 0] = r
                buf[y, sx, 1] = g
                buf[y, sx, 2] = b
    # Horizontal lines (same logic as vertical).
    for yw in range(y_start, y_end+1, 10):
        sy = int(yw * zoom + pan_y)
        if sy < 0 or sy >= h: continue
        is_major = (yw % 50 == 0)
        is_axis = (yw == 0)

        if is_axis: r,g,b = 100, 200, 100      # green axis
        elif is_major: r,g,b = 180, 180, 180   # major line
        else: r,g,b = 218, 218, 218            # minor line

        for x in range(w):
            if is_axis or solid_centimeter_grid:
                buf[sy, x, 0] = r
                buf[sy, x, 1] = g
                buf[sy, x, 2] = b
            else:
                if x % 3 != 0: continue
                buf[sy, x, 0] = r
                buf[sy, x, 1] = g
                buf[sy, x, 2] = b
