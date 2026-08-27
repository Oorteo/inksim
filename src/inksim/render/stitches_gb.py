"""Deferred (G-buffer) stitch renderer producing a continuous satin surface.

Traditional per-stitch renderers shade every stitch as an isolated
cylinder, which produces repeating dark gaps and scattered highlights in
satin areas. This renderer splits the work into two passes, similar to a
deferred shading pipeline:

1. Rasterization: every stitch writes surface attributes (lateral surface
   normal, thread tangent, thread colour, coverage) into per-pixel
   G-buffers. Overlapping stitches accumulate, so neighbouring threads
   merge into one continuous surface instead of isolated tubes.
2. Shading: every covered pixel is lit once from the merged attributes
   using Kajiya-Kay anisotropic specular sheen, fibre-aligned
   micro-striations and curvature-based ambient occlusion.

The result is a continuous glossy ribbon look. It is intentionally an
approximation of real embroidery thread, not a physically accurate model
of twisted ply.
"""

import numba
import numpy as np

from ..constants import MAX_RENDER_LINE_WIDTH_PX

# View-space light direction, shared with the other renderers (upper left).
GB_LIGHT_X, GB_LIGHT_Y, GB_LIGHT_Z = -0.4, -0.4, 0.82

# Single-slot cache for the G-buffers so repeated frames of the same
# viewport size do not reallocate tens of megabytes per frame.
_GB_CACHE_KEY = None
_GB_NORMAL = None
_GB_TANGENT = None
_GB_COLOR = None
_GB_WEIGHT = None


def _get_gbuffers(height, width):
    """Return zeroed G-buffers for the given size, reusing the last ones.

    ``g_normal`` accumulates the lateral (x, y) surface normal; the z
    component is recovered at shade time from the remaining length.
    """
    global _GB_CACHE_KEY, _GB_NORMAL, _GB_TANGENT, _GB_COLOR, _GB_WEIGHT
    key = (height, width)
    if _GB_CACHE_KEY == key:
        _GB_NORMAL.fill(0.0)
        _GB_TANGENT.fill(0.0)
        _GB_COLOR.fill(0.0)
        _GB_WEIGHT.fill(0.0)
        return _GB_NORMAL, _GB_TANGENT, _GB_COLOR, _GB_WEIGHT
    _GB_NORMAL = np.zeros((height, width, 2), dtype=np.float32)
    _GB_TANGENT = np.zeros((height, width, 2), dtype=np.float32)
    _GB_COLOR = np.zeros((height, width, 4), dtype=np.float32)
    _GB_WEIGHT = np.zeros((height, width), dtype=np.float32)
    _GB_CACHE_KEY = key
    return _GB_NORMAL, _GB_TANGENT, _GB_COLOR, _GB_WEIGHT


def render_realistic_gbuffer_numba(
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
    """Render stitches as one continuous shaded thread surface.

    ``buf`` is an RGB(A) uint8 image with the background (plain, fabric or
    grid) already composited. Stitches are ``[x1, y1, x2, y2, r, g, b]``
    rows in millimetres; ``zoom``/``pan`` map them to pixel coordinates.
    The G-buffer merges neighbouring threads into a continuous satin ribbon.
    It is an approximation, not a full physical thread model.
    """
    height, width = buf.shape[0], buf.shape[1]
    thread_radius = min(
        MAX_RENDER_LINE_WIDTH_PX * 0.5,
        max(1.3, line_width * zoom * 0.5),
    )
    if visible_count <= 0:
        return
    g_normal, g_tangent, g_color, g_weight = _get_gbuffers(height, width)
    _gb_rasterize(
        g_normal,
        g_tangent,
        g_color,
        g_weight,
        stitches,
        visible_count,
        zoom,
        pan_x,
        pan_y,
        thread_radius,
    )
    _gb_shade(buf, g_normal, g_tangent, g_color, g_weight, dark_factor, light_factor, thread_radius)


@numba.njit(cache=True)
def _gb_rasterize(
    g_normal,
    g_tangent,
    g_color,
    g_weight,
    stitches,
    visible_count,
    zoom,
    pan_x,
    pan_y,
    thread_radius,
):
    """Rasterize stitch capsules, accumulating surface attributes.

    Attributes are weighted by pixel coverage so partially covered edge
    pixels blend smoothly. Colour is weighted by coverage squared, which
    keeps the most fully covered (top) thread dominant where layers meet.
    """
    aa_edge = 0.5
    reach = thread_radius + aa_edge

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

        margin = int(np.ceil(thread_radius + aa_edge + 1.0))
        min_x = max(0, int(np.floor(min(x1, x2) - margin)))
        max_x = min(g_weight.shape[1] - 1, int(np.ceil(max(x1, x2) + margin)))
        min_y = max(0, int(np.floor(min(y1, y2) - margin)))
        max_y = min(g_weight.shape[0] - 1, int(np.ceil(max(y1, y2) + margin)))
        if min_x > max_x or min_y > max_y:
            continue

        r_base = stitches[i, 4]
        g_base = stitches[i, 5]
        b_base = stitches[i, 6]

        for py in range(min_y, max_y + 1):
            fy = (py + 0.5) - y1
            for px in range(min_x, max_x + 1):
                fx = (px + 0.5) - x1
                along = fx * tx + fy * ty
                if along < 0.0:
                    end_x = fx
                    end_y = fy
                    distance = np.sqrt(end_x * end_x + end_y * end_y)
                elif along > length:
                    end_x = fx - dx
                    end_y = fy - dy
                    distance = np.sqrt(end_x * end_x + end_y * end_y)
                else:
                    distance = abs(fx * nx + fy * ny)
                if distance > reach:
                    continue

                # Standard SDF antialiasing: full coverage inside the
                # thread core, a one-pixel falloff band at the edge.
                coverage = (reach - distance) / (2.0 * aa_edge)
                coverage = min(max(coverage, 0.0), 1.0)

                # Lateral surface position on the unit cylinder cross
                # section. The 2D normal contribution is invariant under a
                # tangent sign flip, so opposing stitch directions merge.
                across = (fx * nx + fy * ny) / thread_radius
                if across > 1.0:
                    across = 1.0
                elif across < -1.0:
                    across = -1.0

                g_weight[py, px] += coverage
                g_normal[py, px, 0] += nx * across * coverage
                g_normal[py, px, 1] += ny * across * coverage

                color_weight = coverage * coverage
                g_color[py, px, 0] += r_base * color_weight
                g_color[py, px, 1] += g_base * color_weight
                g_color[py, px, 2] += b_base * color_weight
                g_color[py, px, 3] += color_weight

                # Tangent: keep a stable sign by aligning with what is
                # already accumulated, so zigzag fills keep a usable
                # averaged direction instead of cancelling to zero. Use
                # temporary copies so the per-stitch loop variables are not
                # mutated when opposing directions overlap.
                old_weight = g_weight[py, px] - coverage
                old_x = g_tangent[py, px, 0]
                old_y = g_tangent[py, px, 1]
                if old_weight <= 1e-6:
                    g_tangent[py, px, 0] = tx * coverage
                    g_tangent[py, px, 1] = ty * coverage
                else:
                    tmp_tx = tx
                    tmp_ty = ty
                    if old_x * tmp_tx + old_y * tmp_ty < 0.0:
                        tmp_tx = -tmp_tx
                        tmp_ty = -tmp_ty
                    g_tangent[py, px, 0] = old_x + tmp_tx * coverage
                    g_tangent[py, px, 1] = old_y + tmp_ty * coverage

        # U-turn fill: consecutive satin stitches share an endpoint where
        # the thread reverses direction. The two capsules leave a V-shaped
        # wedge between them that no single capsule covers, yet a real
        # thread bends continuously through the turn. Fill that wedge by
        # rasterizing a disc centred on the shared endpoint.
        if i + 1 < visible_count:
            npx = stitches[i + 1, 0] * zoom + pan_x
            npy = stitches[i + 1, 1] * zoom + pan_y
            if abs(x2 - npx) < 0.5 and abs(y2 - npy) < 0.5:
                _gb_rasterize_disc(
                    g_normal,
                    g_tangent,
                    g_color,
                    g_weight,
                    (x2 + npx) * 0.5,
                    (y2 + npy) * 0.5,
                    r_base,
                    g_base,
                    b_base,
                    thread_radius,
                    aa_edge,
                )


@numba.njit(cache=True)
def _gb_rasterize_segment(
    g_normal,
    g_tangent,
    g_color,
    g_weight,
    x1,
    y1,
    x2,
    y2,
    r_base,
    g_base,
    b_base,
    thread_radius,
    aa_edge,
):
    """Rasterize one capsule with attribute accumulation (shared by the
    main stitch pass and the U-turn fill segments)."""
    dx = x2 - x1
    dy = y2 - y1
    length_squared = dx * dx + dy * dy
    if length_squared <= 0.0:
        return
    length = np.sqrt(length_squared)
    tx = dx / length
    ty = dy / length
    nx = -ty
    ny = tx

    reach = thread_radius + aa_edge
    margin = int(np.ceil(thread_radius + aa_edge + 1.0))
    min_x = max(0, int(np.floor(min(x1, x2) - margin)))
    max_x = min(g_weight.shape[1] - 1, int(np.ceil(max(x1, x2) + margin)))
    min_y = max(0, int(np.floor(min(y1, y2) - margin)))
    max_y = min(g_weight.shape[0] - 1, int(np.ceil(max(y1, y2) + margin)))
    if min_x > max_x or min_y > max_y:
        return

    for py in range(min_y, max_y + 1):
        fy = (py + 0.5) - y1
        for px in range(min_x, max_x + 1):
            fx = (px + 0.5) - x1
            along = fx * tx + fy * ty
            if along < 0.0:
                end_x = fx
                end_y = fy
                distance = np.sqrt(end_x * end_x + end_y * end_y)
            elif along > length:
                end_x = fx - dx
                end_y = fy - dy
                distance = np.sqrt(end_x * end_x + end_y * end_y)
            else:
                distance = abs(fx * nx + fy * ny)
            if distance > reach:
                continue

            coverage = (reach - distance) / (2.0 * aa_edge)
            coverage = min(max(coverage, 0.0), 1.0)

            across = (fx * nx + fy * ny) / thread_radius
            if across > 1.0:
                across = 1.0
            elif across < -1.0:
                across = -1.0

            g_weight[py, px] += coverage
            g_normal[py, px, 0] += nx * across * coverage
            g_normal[py, px, 1] += ny * across * coverage

            color_weight = coverage * coverage
            g_color[py, px, 0] += r_base * color_weight
            g_color[py, px, 1] += g_base * color_weight
            g_color[py, px, 2] += b_base * color_weight
            g_color[py, px, 3] += color_weight

            old_weight = g_weight[py, px] - coverage
            old_x = g_tangent[py, px, 0]
            old_y = g_tangent[py, px, 1]
            if old_weight <= 1e-6:
                g_tangent[py, px, 0] = tx * coverage
                g_tangent[py, px, 1] = ty * coverage
            else:
                tmp_tx = tx
                tmp_ty = ty
                if old_x * tmp_tx + old_y * tmp_ty < 0.0:
                    tmp_tx = -tmp_tx
                    tmp_ty = -tmp_ty
                g_tangent[py, px, 0] = old_x + tmp_tx * coverage
                g_tangent[py, px, 1] = old_y + tmp_ty * coverage


@numba.njit(cache=True)
def _gb_rasterize_disc(
    g_normal,
    g_tangent,
    g_color,
    g_weight,
    cx,
    cy,
    r_base,
    g_base,
    b_base,
    thread_radius,
    aa_edge,
):
    """Rasterize a filled antialiased disc at a satin U-turn endpoint.

    The disc adds coverage and colour in the V-shaped wedge that the two
    meeting capsules do not cover, without contributing a tangent so the
    surrounding thread direction stays intact.
    """
    reach = thread_radius + aa_edge
    margin = int(np.ceil(thread_radius + aa_edge + 1.0))
    min_x = max(0, int(np.floor(cx - margin)))
    max_x = min(g_weight.shape[1] - 1, int(np.ceil(cx + margin)))
    min_y = max(0, int(np.floor(cy - margin)))
    max_y = min(g_weight.shape[0] - 1, int(np.ceil(cy + margin)))
    if min_x > max_x or min_y > max_y:
        return

    for py in range(min_y, max_y + 1):
        fy = (py + 0.5) - cy
        for px in range(min_x, max_x + 1):
            fx = (px + 0.5) - cx
            distance = np.sqrt(fx * fx + fy * fy)
            if distance > reach:
                continue

            coverage = (reach - distance) / (2.0 * aa_edge)
            coverage = min(max(coverage, 0.0), 1.0)

            if distance > 1e-6:
                nx = fx / distance
                ny = fy / distance
            else:
                nx = 0.0
                ny = 0.0

            across = distance / thread_radius
            if across > 1.0:
                across = 1.0
            elif across < -1.0:
                across = -1.0

            g_weight[py, px] += coverage
            g_normal[py, px, 0] += nx * across * coverage
            g_normal[py, px, 1] += ny * across * coverage

            color_weight = coverage * coverage
            g_color[py, px, 0] += r_base * color_weight
            g_color[py, px, 1] += g_base * color_weight
            g_color[py, px, 2] += b_base * color_weight
            g_color[py, px, 3] += color_weight


@numba.njit(cache=True, parallel=True)
def _gb_shade(
    buf,
    g_normal,
    g_tangent,
    g_color,
    g_weight,
    dark_factor,
    light_factor,
    thread_radius,
):
    """Light the merged G-buffer surface and composite it over the buffer."""
    height, width = g_weight.shape
    light_x, light_y, light_z = GB_LIGHT_X, GB_LIGHT_Y, GB_LIGHT_Z
    light_length = np.sqrt(
        light_x * light_x + light_y * light_y + light_z * light_z
    )
    light_x /= light_length
    light_y /= light_length
    light_z /= light_length
    half_x = light_x
    half_y = light_y
    half_z = light_z + 1.0
    half_length = np.sqrt(
        half_x * half_x + half_y * half_y + half_z * half_z
    )
    half_x /= half_length
    half_y /= half_length
    half_z /= half_length

    # Thread look tuning. Dark factor deepens valleys, light factor lifts
    # the lit surface and strengthens the sheen, matching the other modes.
    diffuse_floor = 0.30 + 0.30 * (1.0 - dark_factor)
    dark_scale = 1.0 - 0.45 * dark_factor
    lit_lift = 0.10 + 0.25 * light_factor
    sheen_strength = 0.30 + 0.55 * light_factor
    fiber_strength = 0.035 + 0.05 * light_factor
    ao_floor = 0.42 - 0.12 * dark_factor

    ridge_pitch = max(1.4, thread_radius)
    ridge_frequency = np.pi / ridge_pitch

    for py in numba.prange(height):
        for px in range(width):
            weight = g_weight[py, px]
            if weight <= 1e-6:
                # Pure background: leave the composited buffer untouched.
                continue

            # Weight normalization: the average coverage per contributing
            # thread. Saturated pixels (weight >= 1) read as a solid merged
            # surface, so the surface height is derived from it. Averaging
            # the normals keeps shading stable when many threads overlap.
            normal_x = g_normal[py, px, 0] / weight
            normal_y = g_normal[py, px, 1] / weight
            tilt = np.sqrt(normal_x * normal_x + normal_y * normal_y)
            tilt = min(tilt, 1.0)
            normal_z = np.sqrt(max(0.0, 1.0 - tilt * tilt))
            if tilt > 1e-6:
                normal_x /= tilt
                normal_y /= tilt
            else:
                normal_x = 0.0
                normal_y = 0.0

            tangent_x = g_tangent[py, px, 0] / weight
            tangent_y = g_tangent[py, px, 1] / weight
            tangent_length = np.sqrt(
                tangent_x * tangent_x + tangent_y * tangent_y
            )

            # Colour uses its own accumulated weight (coverage squared per
            # stitch), so fully covered pixels keep the exact thread colour
            # and gap pixels darken smoothly instead of dropping to black.
            color_total = g_color[py, px, 3]
            color_total = max(color_total, 1e-6)
            thread_r = g_color[py, px, 0] / color_total
            thread_g = g_color[py, px, 1] / color_total
            thread_b = g_color[py, px, 2] / color_total

            # Surface height model: fully covered pixels are the top of the
            # satin ribbon; partially covered gaps sit lower. Combined with
            # curvature AO this produces the continuous lit ribbon look.
            surface_height = min(weight / 0.9, 1.0)

            # Curvature ambient occlusion: valleys between merged threads
            # have sideways normals and sink into shadow.
            ao = ao_floor + (1.0 - ao_floor) * normal_z
            ao = ao * surface_height + (1.0 - surface_height)

            ndotl = (
                normal_x * light_x + normal_y * light_y + normal_z * light_z
            )
            ndotl = max(ndotl, 0.0)
            diffuse = diffuse_floor + (1.0 - diffuse_floor) * ndotl

            # Kajiya-Kay anisotropic sheen: sin(theta) between the light and
            # the tangent times sin(phi) between the half vector and the
            # tangent. Both terms use positive square roots, so the crown
            # facing the light shows the streak regardless of the thread
            # direction sign; the highlight automatically stretches along
            # the merged thread direction.
            sheen = 0.0
            if tangent_length > 1e-4:
                tangent_x /= tangent_length
                tangent_y /= tangent_length
                tdotl = tangent_x * light_x + tangent_y * light_y
                tdoth = tangent_x * half_x + tangent_y * half_y
                tdoth = min(max(tdoth, -1.0), 1.0)
                sin_theta = np.sqrt(max(0.0, 1.0 - tdotl * tdotl))
                sin_phi = np.sqrt(max(0.0, 1.0 - tdoth * tdoth))
                aniso = sin_theta * sin_phi
                if aniso > 0.0:
                    along_px = px * tangent_x + py * tangent_y
                    # Slow axial shimmer keeps the sheen from looking
                    # like a flat painted stripe along straight threads.
                    shimmer = 0.85 + 0.15 * np.sin(along_px * 0.35 + 1.7)
                    sheen = aniso ** 10.0 * shimmer

            # Fibre micro-texture: fine ridges perpendicular to the merged
            # thread direction emulate individual fibre bundles.
            across_px = px * normal_x + py * normal_y
            fiber = np.sin(across_px * ridge_frequency) * fiber_strength

            r_dark = thread_r * dark_scale * ao
            g_dark = thread_g * dark_scale * ao
            b_dark = thread_b * dark_scale * ao
            r_lit = thread_r + (255.0 - thread_r) * lit_lift
            g_lit = thread_g + (255.0 - thread_g) * lit_lift
            b_lit = thread_b + (255.0 - thread_b) * lit_lift

            intensity = diffuse + fiber
            rr = r_dark + (r_lit - r_dark) * intensity
            gg = g_dark + (g_lit - g_dark) * intensity
            bb = b_dark + (b_lit - b_dark) * intensity

            gloss = sheen * sheen_strength
            # Sheen concentrates on the exposed top surface; gaps stay matte.
            gloss = gloss * (0.35 + 0.65 * surface_height)
            rr = rr + gloss * (255.0 - rr)
            gg = gg + gloss * (255.0 - gg)
            bb = bb + gloss * (255.0 - bb)

            coverage = min(weight, 1.0)
            inv_coverage = 1.0 - coverage
            background_r = buf[py, px, 0]
            background_g = buf[py, px, 1]
            background_b = buf[py, px, 2]

            out_r = background_r * inv_coverage + rr * coverage
            out_g = background_g * inv_coverage + gg * coverage
            out_b = background_b * inv_coverage + bb * coverage
            out_r = min(out_r, 255.0)
            out_g = min(out_g, 255.0)
            out_b = min(out_b, 255.0)
            buf[py, px, 0] = int(out_r)
            buf[py, px, 1] = int(out_g)
            buf[py, px, 2] = int(out_b)