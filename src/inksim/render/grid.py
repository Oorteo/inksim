import numba
import numpy as np

@numba.njit
def render_grid_numba(buf, zoom, pan_x, pan_y):
    # Draw 1 cm helper grid into the RGB buffer.
    # - every 10 mm: minor grid line
    # - every 50 mm: major grid line
    # - x=0 / y=0: highlighted axes
    # zoom converts mm -> pixels, pan is screen-space origin offset.
    h, w, _ = buf.shape

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

    # Vertical lines.
    for xw in range(x_start, x_end+1, 10):
        # Project world x to screen x.
        sx = int(xw * zoom + pan_x)
        if sx < 0 or sx >= w: continue

        # Choose line style.
        is_major = (xw % 50 == 0)
        is_axis = (xw == 0)

        if is_axis: r,g,b = 200, 100, 100      # red axis
        elif is_major: r,g,b = 190, 190, 190   # major line
        else: r,g,b = 230, 230, 230            # minor line

        # Keep minor/major lines subtle using a dotted pattern.
        for y in range(h):
            if is_axis:
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
        elif is_major: r,g,b = 190, 190, 190   # major line
        else: r,g,b = 230, 230, 230            # minor line

        for x in range(w):
            if is_axis:
                buf[sy, x, 0] = r
                buf[sy, x, 1] = g
                buf[sy, x, 2] = b
            else:
                if x % 3 != 0: continue
                buf[sy, x, 0] = r
                buf[sy, x, 1] = g
                buf[sy, x, 2] = b
