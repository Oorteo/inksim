from ..constants import DENSITY_CRITICAL_PER_MM2, DENSITY_RADIUS_MM, DENSITY_WARNING_PER_MM2
import numba
import numpy as np

@numba.njit
def calculate_stitch_density_numba(points, min_x, min_y, max_x, max_y):
    """Calculate stitch endpoints per square millimeter in a 5 mm circle."""
    point_count = points.shape[0]
    density = np.zeros(point_count, dtype=np.float32)
    if point_count == 0:
        return density

    cell_size = 1.0
    grid_width = max(1, int(np.ceil((max_x - min_x) / cell_size)) + 1)
    grid_height = max(1, int(np.ceil((max_y - min_y) / cell_size)) + 1)
    grid = np.zeros((grid_height, grid_width), dtype=np.int32)

    for point_index in range(point_count):
        cell_x = int((points[point_index, 0] - min_x) / cell_size)
        cell_y = int((points[point_index, 1] - min_y) / cell_size)
        cell_x = min(max(cell_x, 0), grid_width - 1)
        cell_y = min(max(cell_y, 0), grid_height - 1)
        grid[cell_y, cell_x] += 1

    radius = DENSITY_RADIUS_MM
    radius_cells = int(np.ceil(radius / cell_size))
    radius_squared = radius * radius
    circle_area = np.pi * radius_squared
    for point_index in range(point_count):
        cell_x = int((points[point_index, 0] - min_x) / cell_size)
        cell_y = int((points[point_index, 1] - min_y) / cell_size)
        count = 0
        for offset_y in range(-radius_cells, radius_cells + 1):
            neighbor_y = cell_y + offset_y
            if neighbor_y < 0 or neighbor_y >= grid_height:
                continue
            for offset_x in range(-radius_cells, radius_cells + 1):
                neighbor_x = cell_x + offset_x
                if neighbor_x < 0 or neighbor_x >= grid_width:
                    continue
                cell_center_x = min_x + (neighbor_x + 0.5) * cell_size
                cell_center_y = min_y + (neighbor_y + 0.5) * cell_size
                dx = cell_center_x - points[point_index, 0]
                dy = cell_center_y - points[point_index, 1]
                if dx * dx + dy * dy <= radius_squared + 1.0:
                    count += grid[neighbor_y, neighbor_x]
        density[point_index] = count / circle_area
    return density


@numba.njit
def render_density_numba(buf, points, density, visible_count, zoom, pan_x, pan_y):
    """Render the stitch-density map directly into the RGB buffer."""
    height, width, _ = buf.shape
    visible_points = min(visible_count, points.shape[0])
    for point_index in range(visible_points):
        density_value = density[point_index]
        if density_value >= DENSITY_CRITICAL_PER_MM2:
            r, g, b = 220, 35, 35
        elif density_value >= DENSITY_WARNING_PER_MM2:
            r, g, b = 235, 175, 25
        else:
            r, g, b = 45, 110, 215
        screen_x = int(points[point_index, 0] * zoom + pan_x)
        screen_y = int(points[point_index, 1] * zoom + pan_y)
        if screen_x < -3 or screen_x >= width + 3:
            continue
        if screen_y < -3 or screen_y >= height + 3:
            continue
        for offset_y in range(-3, 4):
            for offset_x in range(-3, 4):
                if offset_x * offset_x + offset_y * offset_y > 9:
                    continue
                pixel_x = screen_x + offset_x
                pixel_y = screen_y + offset_y
                if 0 <= pixel_x < width and 0 <= pixel_y < height:
                    if offset_x * offset_x + offset_y * offset_y <= 1:
                        buf[pixel_y, pixel_x, 0] = 10
                        buf[pixel_y, pixel_x, 1] = 10
                        buf[pixel_y, pixel_x, 2] = 10
                    else:
                        buf[pixel_y, pixel_x, 0] = r
                        buf[pixel_y, pixel_x, 1] = g
                        buf[pixel_y, pixel_x, 2] = b
