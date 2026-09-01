# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

import numba
import numpy as np

@numba.njit(cache=True)
def render_fabric_numba(buf, zoom):
    """Render a lit plain-weave fabric surface at the current zoom."""
    height, width, _ = buf.shape
    thread_spacing = max(1.5, 0.45 * zoom)
    bump_height = 0.08 * thread_spacing
    texture_strength = min(1.0, max(0.0, (thread_spacing - 2.5) / 4.0))
    light_x, light_y, light_z = -0.4, -0.4, 0.82
    light_length = np.sqrt(
        light_x * light_x + light_y * light_y + light_z * light_z
    )
    light_x /= light_length
    light_y /= light_length
    light_z /= light_length
    base_r, base_g, base_b = 238, 235, 228

    for y in range(height):
        for x in range(width):
            cell_x = int(x // thread_spacing)
            cell_y = int(y // thread_spacing)
            u = (x % thread_spacing) / thread_spacing
            v = (y % thread_spacing) / thread_spacing
            is_warp = (cell_x + cell_y) % 2 == 0

            hash_value = np.sin(x * 12.9898 + y * 78.233) * 43758.5453
            fiber_noise = (hash_value - np.floor(hash_value)) * 0.08 - 0.04

            if is_warp:
                distance = (u - 0.5) * 2.0
                dz_dx = -2.0 * distance * (2.0 / thread_spacing) * bump_height
                dz_dy = np.sin((v - 0.5) * np.pi) * 0.15
            else:
                distance = (v - 0.5) * 2.0
                dz_dx = np.sin((u - 0.5) * np.pi) * 0.15
                dz_dy = -2.0 * distance * (2.0 / thread_spacing) * bump_height

            normal_x = -dz_dx
            normal_y = -dz_dy
            normal_z = 1.0
            normal_length = np.sqrt(
                normal_x * normal_x
                + normal_y * normal_y
                + normal_z * normal_z
            )
            normal_x /= normal_length
            normal_y /= normal_length
            normal_z /= normal_length
            diffuse = max(
                0.0,
                normal_x * light_x
                + normal_y * light_y
                + normal_z * light_z,
            )
            gap_factor = 1.0 - 0.30 * (abs(distance) ** 4)
            textured_shading = (
                (0.52 + 0.48 * diffuse) * gap_factor + fiber_noise
            )
            shading = 1.0 + (textured_shading - 1.0) * texture_strength
            shading = max(0.35, min(1.15, shading))
            buf[y, x, 0] = max(0, min(255, int(base_r * shading)))
            buf[y, x, 1] = max(0, min(255, int(base_g * shading)))
            buf[y, x, 2] = max(0, min(255, int(base_b * shading)))
