import numba
import numpy as np

from ..constants import MAX_RENDER_LINE_WIDTH_PX, MAX_RENDER_STEPS


@numba.njit(cache=True)
def render_realistic_numba(
    buf,
    stitches,
    visible_count,
    zoom,
    pan_x,
    pan_y,
    line_width,
    dark_factor,
    light_factor,
):
    """Render stitches as lit cylindrical threads with soft cast shadows.

    This is an intentionally approximate per-stitch model. Its isolated
    cylinders can exaggerate sewing direction and dark gaps, especially in
    satin areas; a future renderer should use a continuous anisotropic satin
    surface or normal map for more faithful results.
    """
    height, width, _ = buf.shape
    thread_radius = max(0.75, line_width * zoom * 0.5)
    margin = int(np.ceil(thread_radius + 4.0))

    light_x, light_y, light_z = -0.4, -0.4, 0.82
    light_length = np.sqrt(
        light_x * light_x + light_y * light_y + light_z * light_z
    )
    light_x /= light_length
    light_y /= light_length
    light_z /= light_length
    shadow_dx = int(np.round(-light_x * thread_radius * 1.4))
    shadow_dy = int(np.round(-light_y * thread_radius * 1.4))
    half_x = light_x
    half_y = light_y
    half_z = light_z + 1.0
    half_length = np.sqrt(
        half_x * half_x + half_y * half_y + half_z * half_z
    )
    half_x /= half_length
    half_y /= half_length
    half_z /= half_length

    for i in range(visible_count):
        x1 = stitches[i, 0] * zoom + pan_x
        y1 = stitches[i, 1] * zoom + pan_y
        x2 = stitches[i, 2] * zoom + pan_x
        y2 = stitches[i, 3] * zoom + pan_y
        dx = x2 - x1
        dy = y2 - y1
        length = np.sqrt(dx * dx + dy * dy)
        if length <= 0.1:
            continue
        tx = dx / length
        ty = dy / length
        nx = -ty
        ny = tx

        min_x = max(0, int(np.floor(min(x1, x2) - margin + shadow_dx)))
        max_x = min(width - 1, int(np.ceil(max(x1, x2) + margin + shadow_dx)))
        min_y = max(0, int(np.floor(min(y1, y2) - margin + shadow_dy)))
        max_y = min(height - 1, int(np.ceil(max(y1, y2) + margin + shadow_dy)))
        for py in range(min_y, max_y + 1):
            for px in range(min_x, max_x + 1):
                vx = (px - shadow_dx) - x1
                vy = (py - shadow_dy) - y1
                along = vx * tx + vy * ty
                if along < 0.0:
                    distance = np.sqrt(vx * vx + vy * vy)
                elif along > length:
                    end_x = vx - dx
                    end_y = vy - dy
                    distance = np.sqrt(end_x * end_x + end_y * end_y)
                else:
                    distance = abs(vx * nx + vy * ny)
                if distance <= thread_radius + 1.5:
                    shadow_alpha = 1.0 - distance / (thread_radius + 1.5)
                    shadow_alpha = shadow_alpha * shadow_alpha * 0.28
                    buf[py, px, 0] = int(buf[py, px, 0] * (1.0 - shadow_alpha))
                    buf[py, px, 1] = int(buf[py, px, 1] * (1.0 - shadow_alpha))
                    buf[py, px, 2] = int(buf[py, px, 2] * (1.0 - shadow_alpha))

        r_base = int(stitches[i, 4])
        g_base = int(stitches[i, 5])
        b_base = int(stitches[i, 6])
        r_dark = r_base * (0.88 + 0.12 * dark_factor)
        g_dark = g_base * (0.88 + 0.12 * dark_factor)
        b_dark = b_base * (0.88 + 0.12 * dark_factor)
        r_light = r_base + (255 - r_base) * min(1.0, light_factor + 0.15)
        g_light = g_base + (255 - g_base) * min(1.0, light_factor + 0.15)
        b_light = b_base + (255 - b_base) * min(1.0, light_factor + 0.15)
        r_bright = min(255.0, r_base * 1.15 + 20.0)
        g_bright = min(255.0, g_base * 1.15 + 20.0)
        b_bright = min(255.0, b_base * 1.15 + 20.0)

        min_x = max(0, int(np.floor(min(x1, x2) - margin)))
        max_x = min(width - 1, int(np.ceil(max(x1, x2) + margin)))
        min_y = max(0, int(np.floor(min(y1, y2) - margin)))
        max_y = min(height - 1, int(np.ceil(max(y1, y2) + margin)))
        for py in range(min_y, max_y + 1):
            for px in range(min_x, max_x + 1):
                vx = px - x1
                vy = py - y1
                along = vx * tx + vy * ty
                if along < 0.0:
                    distance = np.sqrt(vx * vx + vy * vy)
                    along_pos = 0.0
                elif along > length:
                    end_x = vx - dx
                    end_y = vy - dy
                    distance = np.sqrt(end_x * end_x + end_y * end_y)
                    along_pos = length
                else:
                    distance = abs(vx * nx + vy * ny)
                    along_pos = along
                if distance > thread_radius + 0.5:
                    continue

                alpha = min(1.0, max(0.0, thread_radius + 0.5 - distance))
                across = max(-1.0, min(1.0, (vx * nx + vy * ny) / thread_radius))
                cylinder = np.sqrt(max(0.0, 1.0 - across * across))
                twist = np.sin((along_pos / max(1.0, thread_radius * 4.0)) * 2.0 * np.pi) * 0.10
                surface_x = nx * across + tx * twist
                surface_y = ny * across + ty * twist
                surface_z = cylinder
                surface_length = np.sqrt(
                    surface_x * surface_x
                    + surface_y * surface_y
                    + surface_z * surface_z
                )
                surface_x /= surface_length
                surface_y /= surface_length
                surface_z /= surface_length
                diffuse = max(
                    0.0,
                    surface_x * light_x
                    + surface_y * light_y
                    + surface_z * light_z,
                )
                specular = max(
                    0.0,
                    surface_x * half_x
                    + surface_y * half_y
                    + surface_z * half_z,
                ) ** 24 * 0.65
                edge_light = 0.35 + 0.65 * cylinder
                intensity = (0.25 + 0.75 * diffuse) * edge_light
                rr = min(255.0, r_dark + (r_light - r_dark) * intensity + specular * 255.0)
                gg = min(255.0, g_dark + (g_light - g_dark) * intensity + specular * 255.0)
                bb = min(255.0, b_dark + (b_light - b_dark) * intensity + specular * 255.0)
                rr = rr * 0.85 + r_bright * 0.15
                gg = gg * 0.85 + g_bright * 0.15
                bb = bb * 0.85 + b_bright * 0.15
                buf[py, px, 0] = int(buf[py, px, 0] * (1.0 - alpha) + rr * alpha)
                buf[py, px, 1] = int(buf[py, px, 1] * (1.0 - alpha) + gg * alpha)
                buf[py, px, 2] = int(buf[py, px, 2] * (1.0 - alpha) + bb * alpha)


@numba.njit(cache=True)
def render_shaded_volume_natural_numba(
    buf,
    stitches,
    visible_count,
    zoom,
    pan_x,
    pan_y,
    line_width,
    dark_factor,
    light_factor,
):
    """Render volume-shaded stitches with subtle per-stitch shade variation."""
    height, width, _ = buf.shape
    effective_width = min(
        MAX_RENDER_LINE_WIDTH_PX,
        max(1.5, line_width * zoom),
    )
    half_width = effective_width * 0.5
    margin = int(np.ceil(half_width + 1.5))

    for i in range(visible_count):
        x1 = stitches[i, 0] * zoom + pan_x
        y1 = stitches[i, 1] * zoom + pan_y
        x2 = stitches[i, 2] * zoom + pan_x
        y2 = stitches[i, 3] * zoom + pan_y
        dx = x2 - x1
        dy = y2 - y1
        length_squared = dx * dx + dy * dy
        if length_squared <= 0.0:
            continue
        length = np.sqrt(length_squared)
        tx = dx / length
        ty = dy / length
        nx = -ty
        ny = tx

        min_x = max(0, int(np.floor(min(x1, x2) - margin)))
        max_x = min(width - 1, int(np.ceil(max(x1, x2) + margin)))
        min_y = max(0, int(np.floor(min(y1, y2) - margin)))
        max_y = min(height - 1, int(np.ceil(max(y1, y2) + margin)))

        r_base = int(stitches[i, 4])
        g_base = int(stitches[i, 5])
        b_base = int(stitches[i, 6])
        phase_seed = np.sin(
            (stitches[i, 0] + stitches[i, 2]) * 17.13
            + (stitches[i, 1] + stitches[i, 3]) * 31.71
            + i * 11.37
            + r_base * 0.013
            + g_base * 0.021
            + b_base * 0.034
        ) * 43758.5453
        phase = phase_seed - np.floor(phase_seed)
        dark_variation = 0.96 + 0.08 * phase
        light_variation = 0.96 + 0.08 * (1.0 - phase)
        r_dark = r_base * (0.65 + 0.35 * dark_factor) * dark_variation
        g_dark = g_base * (0.65 + 0.35 * dark_factor) * dark_variation
        b_dark = b_base * (0.65 + 0.35 * dark_factor) * dark_variation
        light_amount = min(1.0, 0.35 + 0.9 * light_factor)
        r_light = (r_base + (255 - r_base) * light_amount) * light_variation
        g_light = (g_base + (255 - g_base) * light_amount) * light_variation
        b_light = (b_base + (255 - b_base) * light_amount) * light_variation

        for py in range(min_y, max_y + 1):
            for px in range(min_x, max_x + 1):
                vx = px - x1
                vy = py - y1
                along = vx * tx + vy * ty
                if along < 0.0:
                    end_x = vx
                    end_y = vy
                    distance = np.sqrt(end_x * end_x + end_y * end_y)
                    along = 0.0
                elif along > length:
                    end_x = vx - dx
                    end_y = vy - dy
                    distance = np.sqrt(end_x * end_x + end_y * end_y)
                    along = length
                else:
                    distance = abs(vx * nx + vy * ny)
                if distance > half_width + 0.5:
                    continue

                t = along / length
                profile = 1.0 - abs(2.0 * t - 1.0)
                local_variation = 1.0 + 0.025 * np.sin(
                    2.0 * np.pi * t + phase * 2.0 * np.pi
                )
                rr = min(255.0, (r_dark + (r_light - r_dark) * profile) * local_variation)
                gg = min(255.0, (g_dark + (g_light - g_dark) * profile) * local_variation)
                bb = min(255.0, (b_dark + (b_light - b_dark) * profile) * local_variation)
                alpha = min(1.0, max(0.0, half_width + 0.5 - distance))
                buf[py, px, 0] = int(buf[py, px, 0] * (1.0 - alpha) + rr * alpha)
                buf[py, px, 1] = int(buf[py, px, 1] * (1.0 - alpha) + gg * alpha)
                buf[py, px, 2] = int(buf[py, px, 2] * (1.0 - alpha) + bb * alpha)


@numba.njit(cache=True)
def render_realistic_twist_numba(
    buf,
    stitches,
    visible_count,
    zoom,
    pan_x,
    pan_y,
    line_width,
    dark_factor,
    light_factor,
):
    """Render stable cylindrical threads with a subtle symmetric helical sheen."""
    height, width, _ = buf.shape
    thread_radius = max(0.75, line_width * zoom * 0.5)
    margin = int(np.ceil(thread_radius + 1.5))
    twist_pitch = max(2.0, zoom)

    for i in range(visible_count):
        x1 = stitches[i, 0] * zoom + pan_x
        y1 = stitches[i, 1] * zoom + pan_y
        x2 = stitches[i, 2] * zoom + pan_x
        y2 = stitches[i, 3] * zoom + pan_y
        dx = x2 - x1
        dy = y2 - y1
        length_squared = dx * dx + dy * dy
        if length_squared <= 0.0:
            continue
        length = np.sqrt(length_squared)
        tx = dx / length
        ty = dy / length
        nx = -ty
        ny = tx

        min_x = max(0, int(np.floor(min(x1, x2) - margin)))
        max_x = min(width - 1, int(np.ceil(max(x1, x2) + margin)))
        min_y = max(0, int(np.floor(min(y1, y2) - margin)))
        max_y = min(height - 1, int(np.ceil(max(y1, y2) + margin)))

        r_base = int(stitches[i, 4])
        g_base = int(stitches[i, 5])
        b_base = int(stitches[i, 6])
        world_mid_x = (stitches[i, 0] + stitches[i, 2]) * 0.5
        world_mid_y = (stitches[i, 1] + stitches[i, 3]) * 0.5
        phase_seed = np.sin(
            world_mid_x * 12.9898
            + world_mid_y * 78.233
            + i * 37.719
            + r_base * 0.017
            + g_base * 0.031
            + b_base * 0.047
        ) * 43758.5453
        phase = phase_seed - np.floor(phase_seed)
        phase_offset = 2.0 * np.pi * phase
        r_dark = r_base * (0.72 + 0.28 * dark_factor)
        g_dark = g_base * (0.72 + 0.28 * dark_factor)
        b_dark = b_base * (0.72 + 0.28 * dark_factor)
        light_amount = 0.08 + 0.18 * light_factor
        helix_strength = 0.10 + 0.55 * light_factor
        r_light = r_base + (255 - r_base) * light_amount
        g_light = g_base + (255 - g_base) * light_amount
        b_light = b_base + (255 - b_base) * light_amount

        for py in range(min_y, max_y + 1):
            for px in range(min_x, max_x + 1):
                vx = px - x1
                vy = py - y1
                along = vx * tx + vy * ty
                if along < 0.0:
                    distance = np.sqrt(vx * vx + vy * vy)
                    along_pos = 0.0
                elif along > length:
                    end_x = vx - dx
                    end_y = vy - dy
                    distance = np.sqrt(end_x * end_x + end_y * end_y)
                    along_pos = length
                else:
                    across_distance = vx * nx + vy * ny
                    distance = abs(across_distance)
                    along_pos = along
                if distance > thread_radius + 0.5:
                    continue

                across = max(-1.0, min(1.0, (vx * nx + vy * ny) / thread_radius))
                cylinder = np.sqrt(max(0.0, 1.0 - across * across))
                normalized_along = along_pos / length
                symmetric_along = min(normalized_along, 1.0 - normalized_along)
                wave_count = max(1.0, np.floor(length / twist_pitch + 0.5))
                helix = 0.5 + 0.5 * np.cos(
                    2.0 * np.pi * symmetric_along * wave_count
                    + phase_offset
                )
                endpoint_span = min(0.5, 3.0 * thread_radius / length)
                endpoint_position = min(1.0, symmetric_along / endpoint_span)
                endpoint_fade = endpoint_position * endpoint_position
                endpoint_fade = endpoint_fade * (3.0 - 2.0 * endpoint_position)
                helix *= endpoint_fade
                intensity = (
                    0.54
                    + 0.12 * cylinder
                    + helix_strength * (2.0 * helix - 1.0)
                )
                endpoint_shadow = (1.0 - endpoint_fade) * (1.0 - endpoint_fade)
                intensity -= 0.22 * endpoint_shadow
                rr = min(255.0, r_dark + (r_light - r_dark) * intensity)
                gg = min(255.0, g_dark + (g_light - g_dark) * intensity)
                bb = min(255.0, b_dark + (b_light - b_dark) * intensity)

                alpha = min(1.0, max(0.0, thread_radius + 0.5 - distance))
                buf[py, px, 0] = int(buf[py, px, 0] * (1.0 - alpha) + rr * alpha)
                buf[py, px, 1] = int(buf[py, px, 1] * (1.0 - alpha) + gg * alpha)
                buf[py, px, 2] = int(buf[py, px, 2] * (1.0 - alpha) + bb * alpha)


@numba.njit(cache=True)
def render_shaded_numba(
    buf,
    stitches,
    visible_count,
    zoom,
    pan_x,
    pan_y,
    use_shaded,
    line_width,
    dark_factor,
    light_factor,
    use_realistic=False,
):
    # Draw visible stitch segments into the RGB buffer.
    # Each segment is [x1, y1, x2, y2, r, g, b] in mm + base thread color.
    # We project mm -> screen pixels using zoom/pan and then rasterize.
    h, w, _ = buf.shape
    # The configured width is in mm; convert it to screen pixels with the
    # world-to-screen transform so thread thickness follows the design.
    # Realistic must keep same width as shaded to avoid thick blurry look.
    minimum_line_width = 1.5 if use_shaded else 1.0
    effective_line_width = min(
        MAX_RENDER_LINE_WIDTH_PX,
        max(minimum_line_width, line_width * zoom),
    )
    hw = effective_line_width * 0.5
    lw_int = max(1, int(np.ceil(effective_line_width)))

    for i in range(visible_count):
        # Convert segment endpoints from world space (mm) to screen pixels.
        x1 = stitches[i,0] * zoom + pan_x
        y1 = stitches[i,1] * zoom + pan_y
        x2 = stitches[i,2] * zoom + pan_x
        y2 = stitches[i,3] * zoom + pan_y

        # Get base thread color for this segment.
        r_base = int(stitches[i, 4])
        g_base = int(stitches[i, 5])
        b_base = int(stitches[i, 6])

        # Cheap reject: ignore segments completely far outside the viewport.
        if (x1 < -200 and x2 < -200) or (x1 > w+200 and x2 > w+200): continue
        if (y1 < -200 and y2 < -200) or (y1 > h+200 and y2 > h+200): continue

        # Compute the segment length in pixels and sample points along it.
        dx = x2 - x1
        dy = y2 - y1
        length = np.sqrt(dx*dx + dy*dy)
        if length <= 0: continue
        normal_x = -dy / length
        normal_y = dx / length

        # Precompute variants for thread shading.
        # For realistic we want brighter variants, not dark mush.
        r_dark = int(r_base * (0.88 + 0.12 * dark_factor))
        g_dark = int(g_base * (0.88 + 0.12 * dark_factor))
        b_dark = int(b_base * (0.88 + 0.12 * dark_factor))
        r_light = int(r_base + (255 - r_base) * min(1.0, light_factor + 0.15))
        g_light = int(g_base + (255 - g_base) * min(1.0, light_factor + 0.15))
        b_light = int(b_base + (255 - b_base) * min(1.0, light_factor + 0.15))
        # Brightened version for satin sheen
        r_bright = int(min(255, r_base * 1.15 + 20))
        g_bright = int(min(255, g_base * 1.15 + 20))
        b_bright = int(min(255, b_base * 1.15 + 20))

        # Oversample short projected stitches so rounded pixel coordinates do
        # not leave gaps while the line width crosses the one-pixel boundary.
        sample_factor = 1.5 if length < 512.0 else 1.0
        steps = min(
            MAX_RENDER_STEPS,
            max(1, int(np.ceil(length * sample_factor))),
        )
        for s in range(steps+1):
            t = s / steps
            x = x1 + dx * t
            y = y1 + dy * t

            # Optional gradient along the segment to make stitches less flat.
            if use_shaded:
                profile = t
                r = int(r_dark + (r_light - r_dark) * profile)
                g = int(g_dark + (g_light - g_dark) * profile)
                b = int(b_dark + (b_light - b_dark) * profile)
            else:
                r = r_base
                g = g_base
                b = b_base

            # Fast path for thin lines (single pixel footprint).
            if lw_int <= 1 and not use_realistic:
                xi = int(x)
                yi = int(y)
                if 0 <= xi < w and 0 <= yi < h:
                    buf[yi, xi, 0] = r
                    buf[yi, xi, 1] = g
                    buf[yi, xi, 2] = b
            else:
                # Thick lines: draw a disk around each sampled point.
                render_radius = hw
                r_loop = lw_int + 1
                for oy in range(-r_loop, r_loop + 1):
                    for ox in range(-r_loop, r_loop + 1):
                        distance_squared = ox*ox + oy*oy
                        if distance_squared > render_radius*render_radius + 0.5:
                            continue
                        xi = int(x + ox)
                        yi = int(y + oy)
                        if 0 <= xi < w and 0 <= yi < h:
                            if use_realistic:
                                # Cylindrical shading - bright center, slightly darker edges
                                normal_position = ox * normal_x + oy * normal_y
                                # -1 .. 1 across the thread width
                                across = normal_position / hw if hw > 0.001 else 0.0
                                across = max(across, -1.0)
                                across = min(across, 1.0)
                                across_abs = across if across >= 0 else -across

                                # Smooth cylinder: 1 - across^2
                                cyl = 1.0 - across_abs * across_abs
                                # Mix dark edge -> bright center
                                rr = int(r_dark + (r_bright - r_dark) * cyl)
                                gg = int(g_dark + (g_bright - g_dark) * cyl)
                                bb = int(b_dark + (b_bright - b_dark) * cyl)

                                # Specular highlight - narrow strip offset from center
                                # Light from top-left -> offset -0.30
                                spec_center = -0.30
                                spec_width = 0.28
                                spec_dist = across - spec_center
                                if spec_dist < 0: spec_dist = -spec_dist
                                if spec_dist < spec_width:
                                    spec = 1.0 - spec_dist / spec_width
                                    spec = spec * spec  # sharper falloff
                                    # Fade specular near stitch ends
                                    along = t if t < 0.5 else 1.0 - t
                                    if along < 0.15:
                                        spec *= along / 0.15
                                    # Add white specular
                                    spec_strength = spec * 0.75
                                    rr = int(rr + (255 - rr) * spec_strength)
                                    gg = int(gg + (255 - gg) * spec_strength)
                                    bb = int(bb + (255 - bb) * spec_strength)

                                # Soft AA on edge only
                                if distance_squared > (hw - 0.6)*(hw - 0.6):
                                    buf[yi, xi, 0] = (buf[yi, xi, 0] + rr) // 2
                                    buf[yi, xi, 1] = (buf[yi, xi, 1] + gg) // 2
                                    buf[yi, xi, 2] = (buf[yi, xi, 2] + bb) // 2
                                else:
                                    buf[yi, xi, 0] = rr
                                    buf[yi, xi, 1] = gg
                                    buf[yi, xi, 2] = bb
                            elif distance_squared <= (hw-0.5)*(hw-0.5):
                                buf[yi, xi, 0] = r
                                buf[yi, xi, 1] = g
                                buf[yi, xi, 2] = b
                            else:
                                buf[yi, xi, 0] = (buf[yi, xi, 0] + r)//2
                                buf[yi, xi, 1] = (buf[yi, xi, 1] + g)//2
                                buf[yi, xi, 2] = (buf[yi, xi, 2] + b)//2


@numba.njit(cache=True)
def render_shaded_volume_numba(
    buf,
    stitches,
    visible_count,
    zoom,
    pan_x,
    pan_y,
    line_width,
    dark_factor,
    light_factor,
):
    """Render shaded stitches with a dark-light-dark axial thread profile."""
    height, width, _ = buf.shape
    effective_width = min(
        MAX_RENDER_LINE_WIDTH_PX,
        max(1.5, line_width * zoom),
    )
    half_width = effective_width * 0.5
    margin = int(np.ceil(half_width + 1.5))

    for i in range(visible_count):
        x1 = stitches[i, 0] * zoom + pan_x
        y1 = stitches[i, 1] * zoom + pan_y
        x2 = stitches[i, 2] * zoom + pan_x
        y2 = stitches[i, 3] * zoom + pan_y
        dx = x2 - x1
        dy = y2 - y1
        length_squared = dx * dx + dy * dy
        if length_squared <= 0.0:
            continue
        length = np.sqrt(length_squared)
        tx = dx / length
        ty = dy / length
        nx = -ty
        ny = tx

        min_x = max(0, int(np.floor(min(x1, x2) - margin)))
        max_x = min(width - 1, int(np.ceil(max(x1, x2) + margin)))
        min_y = max(0, int(np.floor(min(y1, y2) - margin)))
        max_y = min(height - 1, int(np.ceil(max(y1, y2) + margin)))

        r_base = int(stitches[i, 4])
        g_base = int(stitches[i, 5])
        b_base = int(stitches[i, 6])
        r_dark = r_base * (0.65 + 0.35 * dark_factor)
        g_dark = g_base * (0.65 + 0.35 * dark_factor)
        b_dark = b_base * (0.65 + 0.35 * dark_factor)
        light_amount = min(1.0, 0.35 + 0.9 * light_factor)
        r_light = r_base + (255 - r_base) * light_amount
        g_light = g_base + (255 - g_base) * light_amount
        b_light = b_base + (255 - b_base) * light_amount

        for py in range(min_y, max_y + 1):
            for px in range(min_x, max_x + 1):
                vx = px - x1
                vy = py - y1
                along = vx * tx + vy * ty
                if along < 0.0:
                    end_x = vx
                    end_y = vy
                    distance = np.sqrt(end_x * end_x + end_y * end_y)
                    along = 0.0
                elif along > length:
                    end_x = vx - dx
                    end_y = vy - dy
                    distance = np.sqrt(end_x * end_x + end_y * end_y)
                    along = length
                else:
                    distance = abs(vx * nx + vy * ny)
                if distance > half_width + 0.5:
                    continue

                t = along / length
                profile = 1.0 - abs(2.0 * t - 1.0)
                rr = r_dark + (r_light - r_dark) * profile
                gg = g_dark + (g_light - g_dark) * profile
                bb = b_dark + (b_light - b_dark) * profile
                alpha = min(1.0, max(0.0, half_width + 0.5 - distance))
                buf[py, px, 0] = int(buf[py, px, 0] * (1.0 - alpha) + rr * alpha)
                buf[py, px, 1] = int(buf[py, px, 1] * (1.0 - alpha) + gg * alpha)
                buf[py, px, 2] = int(buf[py, px, 2] * (1.0 - alpha) + bb * alpha)

