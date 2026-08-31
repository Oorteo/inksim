"""OpenGL textured-quad stitch renderer for InkSim.

This renderer rasterises stitches as continuous textured ribbon quads
using a normal-map thread texture and Blinn-Phong lighting.  It renders
offscreen into an RGB buffer so it plugs into the existing viewport
pipeline without changing the viewer widget.
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
from PySide6.QtCore import QSize
from PySide6.QtGui import QImage, QOffscreenSurface, QOpenGLContext, QSurfaceFormat
from PySide6.QtOpenGL import (
    QOpenGLBuffer,
    QOpenGLFramebufferObject,
    QOpenGLFramebufferObjectFormat,
    QOpenGLShader,
    QOpenGLShaderProgram,
    QOpenGLTexture,
    QOpenGLVertexArrayObject,
)
from PySide6.QtWidgets import QApplication
from OpenGL.GL import *

VERTEX_SHADER = """
#version 330 core
layout(location = 0) in vec2 a_pos;
layout(location = 1) in vec2 a_uv;
layout(location = 2) in vec3 a_tangent;
layout(location = 3) in vec3 a_bitangent;
layout(location = 4) in vec3 a_normal;
layout(location = 5) in vec3 a_color;
layout(location = 6) in vec2 a_mask;

out vec2 v_uv;
out vec3 v_tangent;
out vec3 v_bitangent;
out vec3 v_normal;
out vec3 v_color;
out vec2 v_mask;

uniform mat4 u_transform;

void main() {
    v_uv = a_uv;
    v_tangent = a_tangent;
    v_bitangent = a_bitangent;
    v_normal = a_normal;
    v_color = a_color;
    v_mask = a_mask;
    gl_Position = u_transform * vec4(a_pos, 0.0, 1.0);
}
"""

FRAGMENT_SHADER = """
#version 330 core

in vec2 v_uv;
in vec3 v_tangent;
in vec3 v_bitangent;
in vec3 v_normal;
in vec3 v_color;
in vec2 v_mask;

out vec4 fragColor;

uniform sampler2D u_texture;
uniform sampler2D u_cap_mask;
uniform vec3 u_light_dir;
uniform float u_k_a;
uniform float u_k_d;
uniform float u_k_s;
uniform float u_specular_exponent;
uniform float u_normal_strength_tangent;
uniform float u_normal_strength_bitangent;

void main() {
    vec4 texel = texture(u_texture, v_uv);
    // Semicircular end-cap mask: white = keep, black = trim. It only bites
    // in the tip overshoot zones (mu < 1 there); over the ribbon body
    // mu = 1 samples the mask's flat side, which stays white across every
    // row where the thread has alpha, so the body alpha is untouched.
    float cap = texture(u_cap_mask, v_mask).r;
    float alpha = texel.a * cap;
    if (alpha < 0.01) {
        discard;
    }

    mat3 TBN = mat3(v_tangent, v_bitangent, v_normal);
    vec3 n = texel.rgb - 0.5;
    n.x *= u_normal_strength_tangent;
    n.y *= u_normal_strength_bitangent;
    vec3 normal = normalize(TBN * n);

    vec3 L = normalize(u_light_dir);
    vec3 V = vec3(0.0, 0.0, 1.0);
    vec3 H = normalize(L + V);

    float ndotl = max(dot(normal, L), 0.0);
    float diffuse = u_k_d * ndotl;
    float specular = u_k_s * pow(max(dot(normal, H), 0.0), u_specular_exponent);

    vec3 shaded = (u_k_a + diffuse) * v_color + vec3(specular);
    // Premultiplied alpha: partially-transparent edge/cap pixels must not
    // emit full lighting, otherwise the straight-alpha fringe makes the
    // thread look dilated at its edges and caps.
    fragColor = vec4(clamp(shaded, 0.0, 1.0) * alpha, alpha);
}
"""


def _default_texture_path() -> Path:
    # Only the packaged asset counts at runtime -- scripts/ is a dev-only
    # texture-generator workspace and is not shipped with the installed app.
    here = Path(__file__).resolve().parent
    candidate = here.parent / "assets" / "thread_textures" / "classic_3strand_normal_mask.png"
    if candidate.exists():
        return candidate
    raise FileNotFoundError(
        f"Thread normal/mask texture not found at {candidate}. "
        "Run scripts/texture/generate_variants.sh to (re)generate it."
    )


_DEFAULT_TEXTURE_PATH = _default_texture_path()


def _default_cap_mask_path() -> Path:
    """Return the semicircle end-cap mask next to the main thread texture.

    May legitimately not exist (older texture sets); callers decide how to
    handle a missing mask (renderers fall back to an all-white 1x1 mask).
    """
    return _DEFAULT_TEXTURE_PATH.with_name(
        _DEFAULT_TEXTURE_PATH.name.replace("_normal_mask", "_cap_mask")
    )


_DEFAULT_CAP_MASK_PATH = _default_cap_mask_path()


def _lighting_coefficients(dark_factor, light_factor):
    """Compute Blinn-Phong coefficients from the shading factors.

    ``light_factor`` lifts the lit surface and strengthens the sheen;
    ``dark_factor`` deepens the shadowed valleys by lowering the ambient
    term (matching the CPU renderers, where a higher dark factor darkens
    the thread).
    """
    k_a = 0.2 + 0.2 * light_factor - 0.15 * dark_factor
    k_d = 0.6 + 0.3 * light_factor
    k_s = 0.4 + 0.3 * light_factor
    return k_a, k_d, k_s


def _normal_strengths(zoom):
    """Return ``(tangent, bitangent)`` normal-map strengths by zoom.

    The normal map's tangent (along-length) component produces the pleasant
    edge-darkening and is kept at full strength. The bitangent (across-width)
    component makes one half of the stitch lit and the other dark; it is
    faded out as the view zooms out so distant stitches stay bright and flat
    instead of disappearing into shadow.

    ``zoom`` is pixels-per-mm; ~4 px/mm is physical (one-to-one) size.
    """
    z = float(np.clip(zoom / 4.0, 0.0, 1.0))
    tangent = 1.0
    bitangent = z
    return tangent, bitangent


def _load_texture(path: Path):
    """Load a PNG as an RGBA uint8 NumPy array using Qt (no PIL dependency)."""
    img = QImage(str(path))
    if img.isNull():
        raise FileNotFoundError(f"Cannot load texture image: {path}")
    img = img.convertToFormat(QImage.Format_RGBA8888)
    width = img.width()
    height = img.height()
    ptr = img.constBits()
    if not isinstance(ptr, memoryview):
        ptr = memoryview(ptr)
    data = np.frombuffer(ptr, dtype=np.uint8).reshape(
        (height, img.bytesPerLine() // 4, 4)
    )[:, :width, :].copy()
    return data, width, height


def load_texture_manifest(path: Path) -> dict:
    """Load the JSON manifest next to a thread texture, if present.

    Returns the manifest dict, or ``{}`` if no manifest exists. The manifest
    carries ``width_fraction`` (fraction of the texture canvas covered by the
    thread) which the renderer uses to normalise ribbon thickness.
    """
    manifest_path = path.with_name(path.stem.replace("_normal_mask", "") + "_manifest.json")
    if not manifest_path.exists():
        # Fall back to a sibling manifest named after the variant directory.
        manifest_path = path.with_name("manifest.json")
    if not manifest_path.exists():
        return {}
    try:
        return json.loads(manifest_path.read_text())
    except (OSError, ValueError):
        return {}


def texture_width_fraction(path: Path) -> float:
    """Return the measured thread width fraction for *path* (default 1.0)."""
    manifest = load_texture_manifest(path)
    value = manifest.get("width_fraction", 1.0)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 1.0


def texture_cap_radius_fraction(path: Path) -> float:
    """Return the cap overshoot fraction for *path* (default 0.0).

    The fraction (of the ribbon height) by which the renderer extends each
    stitch beyond its needle points before the semicircular cap mask is
    applied -- matching the radius measured when the texture was generated.
    """
    manifest = load_texture_manifest(path)
    value = manifest.get("cap_radius_fraction", 0.0)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _build_satin_quads(
    stitches,
    visible_count,
    zoom,
    pan_x,
    pan_y,
    line_width,
    thread_texture_aspect=8.0,
    stitch_height_scale=1.875,
    width_fraction=1.0,
    cap_fraction=0.0,
):
    """Convert stitch segments into textured quad vertex data.

    Returns ``(vertices, indices, index_counts)`` where ``index_counts[i]``
    is the number of index-buffer entries after processing source stitch
    ``i`` (zero-length stitches are skipped and simply repeat the previous
    count). Callers can use this prefix array to draw a sub-range of the
    built geometry (e.g. for timeline scrubbing) without rebuilding it.

    Fully vectorised with NumPy so rebuilding the geometry (e.g. when the
    thread width changes via '[' / ']') stays fast even for large patterns.
    """
    n = int(visible_count)
    empty = (
        np.zeros((0,), dtype=np.float32),
        np.zeros((0,), dtype=np.uint32),
        np.zeros((0,), dtype=np.int64),
    )
    if n == 0:
        return empty

    s = stitches[:n]
    x1 = s[:, 0].astype(np.float64) * zoom + pan_x
    y1 = s[:, 1].astype(np.float64) * zoom + pan_y
    x2 = s[:, 2].astype(np.float64) * zoom + pan_x
    y2 = s[:, 3].astype(np.float64) * zoom + pan_y
    r = s[:, 4] / 255.0
    g = s[:, 5] / 255.0
    b = s[:, 6] / 255.0

    dx = x2 - x1
    dy = y2 - y1
    length = np.hypot(dx, dy)
    valid = length >= 1e-6
    if not valid.any():
        return empty

    inv_len = np.zeros(n, dtype=np.float64)
    np.divide(1.0, length, out=inv_len, where=valid)
    along_x = dx * inv_len
    along_y = dy * inv_len
    across_x = -along_y
    across_y = along_x

    # Full ribbon width in model units. No 1.0 floor: the width must scale
    # with line_width so '[' / ']' actually changes the thread thickness.
    # width_fraction (from the texture manifest) is the fraction of the
    # texture canvas actually covered by the thread; dividing by it makes
    # every variant render at the same physical thickness regardless of how
    # much of the canvas its strands fill.
    stitch_height = max(1e-3, line_width * zoom * stitch_height_scale * 0.5)
    stitch_height /= max(1e-3, width_fraction)
    h = stitch_height / 2.0

    # Ribbon extension beyond the needle points ("tips"). A real thread
    # continues through the needle hole, so the ribbon is lengthened by
    # cap_fraction * ribbon height on both ends and then trimmed to a rounded
    # arc by the semicircular cap mask in the fragment shader.
    overshoot = max(0.0, float(cap_fraction)) * stitch_height

    mx = (x1 + x2) / 2.0
    my = (y1 + y2) / 2.0

    # Ribbon end points sit beyond the needle points (symmetric extension,
    # so the extended segment's midpoint is still the original midpoint).
    # Five columns: tip-S, needle-S, mid, needle-E, tip-E. Tip zones carry
    # cap-mask UVs; the mask's flat white side lands on the needle column.
    rs_x = x1 - along_x * overshoot
    rs_y = y1 - along_y * overshoot
    re_x = x2 + along_x * overshoot
    re_y = y2 + along_y * overshoot
    cols_x = [rs_x, x1, mx, x2, re_x]
    cols_y = [rs_y, y1, my, y2, re_y]

    # ONE global scale for every stitch: U advances at a constant twist
    # density (tiles per mm), so a short and a long stitch both sample the
    # texture at the same rate and look identical. Tiles are laid end to end
    # -- each tile starts exactly where the previous tile ended -- and the
    # LAST tile of a stitch is almost never whole: it is simply cut short at
    # the stitch end (a fragment of the tile covers the remaining length).
    # The next stitch resumes at exactly the U phase where the previous one
    # stopped, so the twist flows continuously across stitch joints.
    # ONE global scale: U advances at a constant twist density (tiles per mm)
    # along the FULL extended ribbon (needle-to-needle length plus both tip
    # overshoots). Tiles chain across stitches, so the twist flows
    # continuously through the needle points.
    repeats = (length + 2.0 * overshoot) / stitch_height / thread_texture_aspect
    repeats = np.maximum(repeats, 1e-6)
    repeats[~valid] = 0.0
    cum = np.cumsum(repeats)
    # U starts one tip-overshoot BEFORE the needle point (the start tip): the
    # same phase window in which the previous stitch's end tip ends, so the
    # two tips at a shared needle point overlap in phase like the physical
    # threads around the needle hole.
    tip_repeats = overshoot / stitch_height / thread_texture_aspect
    texture_ts = np.empty(n, dtype=np.float64)
    texture_ts[0] = -tip_repeats
    texture_ts[1:] = cum[:-1] - tip_repeats
    texture_ts %= 1.0
    texture_ns = texture_ts + tip_repeats
    texture_m = texture_ts + repeats / 2.0
    texture_ne = texture_ts + repeats - tip_repeats
    texture_te = texture_ts + repeats

    # TBN basis. theta = -atan2(along_y, along_x) gives ct = along_x and
    # st = -along_y, so tangent/normal reduce to simple products. The
    # bitangent is tilt-independent: cross(tangent, normal) = (-along_y,
    # -along_x, 0) for every tilt.
    sin60 = math.sin(math.radians(60.0))
    cos60 = math.cos(math.radians(60.0))

    bit_x = -along_y
    bit_y = -along_x
    bit_z = np.zeros(n, dtype=np.float64)

    # start (tilt +60)
    st_tx = cos60 * along_x
    st_ty = -cos60 * along_y
    st_tz = np.full(n, sin60)
    st_nx = -sin60 * along_x
    st_ny = sin60 * along_y
    st_nz = np.full(n, cos60)

    # mid (tilt 0)
    md_tx = along_x
    md_ty = -along_y
    md_tz = np.zeros(n, dtype=np.float64)
    md_nx = np.zeros(n, dtype=np.float64)
    md_ny = np.zeros(n, dtype=np.float64)
    md_nz = np.ones(n, dtype=np.float64)

    # end (tilt -60)
    en_tx = cos60 * along_x
    en_ty = -cos60 * along_y
    en_tz = np.full(n, -sin60)
    en_nx = sin60 * along_x
    en_ny = -sin60 * along_y
    en_nz = np.full(n, cos60)

    # Vertex layout: pos(2), uv(2), tangent(3), bitangent(3), normal(3),
    # color(3), mask(2) = 18 floats. Ten ribbon vertices per stitch -- five
    # columns (tip-S, needle-S, mid, needle-E, tip-E) x upper/lower edge:
    #   0 tS_u  1 nS_u  2 m_u  3 nE_u  4 tE_u  (upper)
    #   5 tS_l  6 nS_l  7 m_l  8 nE_l  9 tE_l  (lower)
    total_verts = 10
    verts = np.empty((n, total_verts, 18), dtype=np.float32)

    # positions (ribbon): five columns, upper = +across, lower = -across
    for ci in range(5):
        cx = cols_x[ci]
        cy = cols_y[ci]
        verts[:, ci, 0] = cx + across_x * h
        verts[:, ci, 1] = cy + across_y * h
        verts[:, ci + 5, 0] = cx - across_x * h
        verts[:, ci + 5, 1] = cy - across_y * h

    # uv (ribbon): U per column, V = 0 upper / 1 lower.
    for ci, uu in enumerate([texture_ts, texture_ns, texture_m, texture_ne, texture_te]):
        verts[:, ci, 2] = uu
        verts[:, ci, 3] = 0.0
        verts[:, ci + 5, 2] = uu
        verts[:, ci + 5, 3] = 1.0

    # tangent + normal: columns 0..1 use the +60 start basis, 2 is flat,
    # 3..4 the -60 end basis (tips shade like their ribbon edge).
    # NOTE: the loop variable must NOT be named `b` -- it would shadow the
    # blue color channel below and corrupt every vertex's blue to the last
    # loop index (the red->magenta / green->cyan color-shift bug).
    for ci in range(5):
        if ci < 2:
            t3 = (st_tx, st_ty, st_tz); n3 = (st_nx, st_ny, st_nz)
        elif ci == 2:
            t3 = (md_tx, md_ty, md_tz); n3 = (md_nx, md_ny, md_nz)
        else:
            t3 = (en_tx, en_ty, en_tz); n3 = (en_nx, en_ny, en_nz)
        for vi in (ci, ci + 5):
            verts[:, vi, 4] = t3[0]; verts[:, vi, 5] = t3[1]; verts[:, vi, 6] = t3[2]
            verts[:, vi, 10] = n3[0]; verts[:, vi, 11] = n3[1]; verts[:, vi, 12] = n3[2]

    # bitangent (tilt-independent) + color
    for v in range(total_verts):
        verts[:, v, 7] = bit_x
        verts[:, v, 8] = bit_y
        verts[:, v, 9] = bit_z
        verts[:, v, 13] = r
        verts[:, v, 14] = g
        verts[:, v, 15] = b

    # mask UVs (attribute 6). The cap-mask texture holds TWO copies of the
    # semicircle side by side -- [as-generated | U-flipped] -- so that the
    # middle seam joins the two FLAT white sides (a fully white column):
    #   start tip: mu 0.0 (outermost) -> 0.5 (needle)  -- LEFT half, apex out,
    #   body:      mu 0.5 (both flat sides joined -> alpha untouched),
    #   end tip:   mu 0.5 (needle) -> 1.0 (outermost)  -- RIGHT half, apex out.
    # mv = V on both tips (upper 0, lower 1). Flipping is done in the
    # texture data, NOT by mirroring mv in the end-tip vertices -- mirroring
    # mv would couple it to U during quad interpolation and sample the mask
    # along a diagonal, producing a skewed cut.
    mu_cols = [0.0, 0.5, 0.5, 0.5, 1.0]
    for ci in range(5):
        verts[:, ci, 16] = mu_cols[ci]
        verts[:, ci, 17] = 0.0
        verts[:, ci + 5, 16] = mu_cols[ci]
        verts[:, ci + 5, 17] = 1.0

    verts = verts[valid].reshape(-1)

    # indices: 24 per stitch (4 quad strips = 8 triangles) over the five
    # columns: (tS,nS) (nS,m) (m,nE) (nE,tE).
    n_valid = int(valid.sum())
    base = np.arange(n_valid, dtype=np.uint32) * total_verts
    per_stitch_idx = 24
    idx = np.empty((n_valid, per_stitch_idx), dtype=np.uint32)
    for seg in range(4):
        a_ = seg
        b_ = seg + 1
        lo = idx[:, seg * 6:seg * 6 + 3]
        hi = idx[:, seg * 6 + 3:(seg + 1) * 6]
        lo[:, 0] = base + a_
        lo[:, 1] = base + b_
        lo[:, 2] = base + a_ + 5
        hi[:, 0] = base + b_
        hi[:, 1] = base + b_ + 5
        hi[:, 2] = base + a_ + 5

    idx = idx.reshape(-1)

    per_stitch = np.where(valid, per_stitch_idx, 0)
    index_counts = np.cumsum(per_stitch).astype(np.int64)

    return verts, idx, index_counts


class _SharedGLContext:
    """Lazily-created offscreen GL context shared by all frames."""

    app = None
    context = None
    surface = None
    program = None
    vao = None
    vbo = None
    ibo = None
    texture = None
    cap_texture = None
    fbo = None
    initialized = False


class _FrameResources:
    """Per-frame vertex/index data and sizes."""

    def __init__(self):
        self.vbo_size = 0
        self.ibo_size = 0
        self.index_count = 0
        self.fbo_size = (0, 0)


def _ensure_qapp():
    if QApplication.instance() is None:
        if not sys.argv:
            sys.argv.append("inksim")
        _SharedGLContext.app = QApplication(sys.argv)


def _init_gl(width, height):
    _ensure_qapp()

    if _SharedGLContext.initialized:
        return

    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    QSurfaceFormat.setDefaultFormat(fmt)

    ctx = QOpenGLContext()
    ctx.setFormat(fmt)
    if not ctx.create():
        raise RuntimeError("Failed to create OpenGL context")

    surface = QOffscreenSurface()
    surface.setFormat(fmt)
    surface.create()

    ctx.makeCurrent(surface)

    _SharedGLContext.context = ctx
    _SharedGLContext.surface = surface

    program = QOpenGLShaderProgram()
    program.addShaderFromSourceCode(QOpenGLShader.Vertex, VERTEX_SHADER)
    program.addShaderFromSourceCode(QOpenGLShader.Fragment, FRAGMENT_SHADER)
    if not program.link():
        raise RuntimeError(f"Shader link failed: {program.log()}")

    _SharedGLContext.program = program

    vao = QOpenGLVertexArrayObject()
    vao.create()

    vbo = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
    vbo.create()
    ibo = QOpenGLBuffer(QOpenGLBuffer.IndexBuffer)
    ibo.create()

    _SharedGLContext.vao = vao
    _SharedGLContext.vbo = vbo
    _SharedGLContext.ibo = ibo

    vao.bind()
    vbo.bind()
    ibo.bind()
    stride = 18 * np.dtype(np.float32).itemsize
    offset = 0
    program.enableAttributeArray(0)
    program.setAttributeBuffer(0, GL_FLOAT, offset, 2, stride)
    offset += 2 * np.dtype(np.float32).itemsize
    program.enableAttributeArray(1)
    program.setAttributeBuffer(1, GL_FLOAT, offset, 2, stride)
    offset += 2 * np.dtype(np.float32).itemsize
    program.enableAttributeArray(2)
    program.setAttributeBuffer(2, GL_FLOAT, offset, 3, stride)
    offset += 3 * np.dtype(np.float32).itemsize
    program.enableAttributeArray(3)
    program.setAttributeBuffer(3, GL_FLOAT, offset, 3, stride)
    offset += 3 * np.dtype(np.float32).itemsize
    program.enableAttributeArray(4)
    program.setAttributeBuffer(4, GL_FLOAT, offset, 3, stride)
    offset += 3 * np.dtype(np.float32).itemsize
    program.enableAttributeArray(5)
    program.setAttributeBuffer(5, GL_FLOAT, offset, 3, stride)
    offset += 3 * np.dtype(np.float32).itemsize
    program.enableAttributeArray(6)
    program.setAttributeBuffer(6, GL_FLOAT, offset, 2, stride)
    vao.release()
    ibo.release()
    vbo.release()

    tex_data, tex_w, tex_h = _load_texture(_DEFAULT_TEXTURE_PATH)
    texture = QOpenGLTexture(QOpenGLTexture.Target2D)
    texture.create()
    texture.setFormat(QOpenGLTexture.RGBAFormat)
    texture.setSize(tex_w, tex_h)
    texture.allocateStorage()
    texture.setData(QOpenGLTexture.RGBA, QOpenGLTexture.UInt8, tex_data.tobytes())
    texture.setMinificationFilter(QOpenGLTexture.LinearMipMapLinear)
    texture.setMagnificationFilter(QOpenGLTexture.Linear)
    texture.setWrapMode(QOpenGLTexture.DirectionS, QOpenGLTexture.Repeat)
    texture.setWrapMode(QOpenGLTexture.DirectionT, QOpenGLTexture.ClampToEdge)
    texture.generateMipMaps()
    _SharedGLContext.texture = texture

    # Semicircular end-cap mask (grayscale, R channel). White = keep, black
    # = trim; sampled only in the tip zones. The texture holds TWO copies of
    # the generated semicircle side by side -- [as-generated | U-flipped]:
    #   LEFT half (start cap, mu 0..0.5): arc apex at mu 0 (the outermost
    #     start tip), flat white side at mu 0.5 (the needle point) -> the
    #     arc bulges backward, away from the stitch body.
    #   RIGHT half (end cap, mu 0.5..1): U-flipped copy -> flat white side
    #     at mu 0.5 (the needle point), apex at mu 1 (the outermost end
    #     tip) -> the arc bulges forward.
    # The seam in the middle therefore joins the two FLAT sides: a fully
    # white column, so the ribbon body (mu = 0.5) stays untouched. (With the
    # halves in the other order the seam would join the two arc APEXES --
    # a black column that punches a hole through the whole body, and both
    # arcs would bulge the wrong way.)
    # A missing mask file falls back to an all-white 1x1 texture, which
    # keeps the ribbon straight-cut.
    cap_path = _DEFAULT_CAP_MASK_PATH
    if cap_path.exists():
        cap_src, cap_w, cap_h = _load_texture(cap_path)
        cap_data = np.concatenate(
            [cap_src, cap_src[:, ::-1, :]], axis=1
        )
        cap_w = cap_data.shape[1]
    else:
        cap_data = np.full((1, 1, 4), 255, dtype=np.uint8)
        cap_w = cap_h = 1
    cap_texture = QOpenGLTexture(QOpenGLTexture.Target2D)
    cap_texture.create()
    cap_texture.setFormat(QOpenGLTexture.RGBAFormat)
    cap_texture.setSize(cap_w, cap_h)
    cap_texture.allocateStorage()
    cap_texture.setData(QOpenGLTexture.RGBA, QOpenGLTexture.UInt8, cap_data.tobytes())
    cap_texture.setMinificationFilter(QOpenGLTexture.Linear)
    cap_texture.setMagnificationFilter(QOpenGLTexture.Linear)
    cap_texture.setWrapMode(QOpenGLTexture.DirectionS, QOpenGLTexture.ClampToEdge)
    cap_texture.setWrapMode(QOpenGLTexture.DirectionT, QOpenGLTexture.ClampToEdge)
    _SharedGLContext.cap_texture = cap_texture

    fbo_format = QOpenGLFramebufferObjectFormat()
    fbo_format.setAttachment(QOpenGLFramebufferObject.CombinedDepthStencil)
    fbo_format.setInternalTextureFormat(GL_RGBA8)
    fbo_format.setMipmap(False)
    fbo = QOpenGLFramebufferObject(QSize(width, height), fbo_format)
    if not fbo.isValid():
        raise RuntimeError("Failed to create framebuffer object")
    _SharedGLContext.fbo = fbo

    glEnable(GL_BLEND)
    # Premultiplied-alpha blending. The fragment shader writes colour
    # already scaled by alpha, so we add it directly and subtract the
    # covered fraction of the background.
    glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA)
    # All quads share z=0 -- stitch layering must follow draw order (later
    # stitch on top), not the depth buffer, so depth testing stays off.
    glDisable(GL_DEPTH_TEST)

    _SharedGLContext.initialized = True


def _resize_fbo(width, height):
    if _SharedGLContext.fbo is None or _SharedGLContext.fbo.size() != QSize(width, height):
        fbo_format = QOpenGLFramebufferObjectFormat()
        fbo_format.setAttachment(QOpenGLFramebufferObject.CombinedDepthStencil)
        fbo_format.setInternalTextureFormat(GL_RGBA8)
        fbo_format.setMipmap(False)
        new_fbo = QOpenGLFramebufferObject(QSize(width, height), fbo_format)
        if not new_fbo.isValid():
            raise RuntimeError("Failed to resize framebuffer object")
        _SharedGLContext.fbo = new_fbo


def _upload_geometry(vertices, indices):
    vbo = _SharedGLContext.vbo
    ibo = _SharedGLContext.ibo
    vbo.bind()
    if vertices.nbytes > vbo.size():
        vbo.allocate(vertices.tobytes(), vertices.nbytes)
    else:
        vbo.write(0, vertices.tobytes(), vertices.nbytes)
    vbo.release()

    ibo.bind()
    if indices.nbytes > ibo.size():
        ibo.allocate(indices.tobytes(), indices.nbytes)
    else:
        ibo.write(0, indices.tobytes(), indices.nbytes)
    ibo.release()


def render_gpu_textured(
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
    """Render visible stitches into *buf* as textured thread quads.

    *buf* is an RGB uint8 NumPy array with the background already drawn.
    The renderer blends the thread on top using the existing alpha mask.
    """
    height, width = buf.shape[:2]
    if visible_count <= 0 or stitches.shape[0] == 0:
        return

    _init_gl(width, height)
    _resize_fbo(width, height)

    _SharedGLContext.context.makeCurrent(_SharedGLContext.surface)

    verts, idx, _index_counts = _build_satin_quads(
        stitches,
        visible_count,
        zoom,
        pan_x,
        pan_y,
        line_width,
        width_fraction=texture_width_fraction(_DEFAULT_TEXTURE_PATH),
        cap_fraction=texture_cap_radius_fraction(_DEFAULT_TEXTURE_PATH),
    )
    if idx.size == 0:
        return

    _upload_geometry(verts, idx)

    fbo = _SharedGLContext.fbo
    fbo.bind()
    glViewport(0, 0, width, height)
    glClearColor(0.0, 0.0, 0.0, 0.0)
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

    program = _SharedGLContext.program
    program.bind()

    # Ortho transform that maps pixel coordinates to NDC.
    sx = 2.0 / width
    sy = -2.0 / height
    tx = -1.0
    ty = 1.0
    transform = np.array([
        sx, 0.0, 0.0, 0.0,
        0.0, sy, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        tx, ty, 0.0, 1.0,
    ], dtype=np.float32)

    glUniformMatrix4fv(program.uniformLocation("u_transform"), 1, GL_FALSE, transform)
    glUniform3f(program.uniformLocation("u_light_dir"), -0.4, -0.4, 0.82)

    # Allow dark/light factors to influence ambient and diffuse lighting.
    k_a, k_d, k_s = _lighting_coefficients(dark_factor, light_factor)
    glUniform1f(program.uniformLocation("u_k_a"), k_a)
    glUniform1f(program.uniformLocation("u_k_d"), k_d)
    glUniform1f(program.uniformLocation("u_k_s"), k_s)
    glUniform1f(program.uniformLocation("u_specular_exponent"), 12.0)
    tangent_strength, bitangent_strength = _normal_strengths(zoom)
    glUniform1f(program.uniformLocation("u_normal_strength_tangent"), tangent_strength)
    glUniform1f(program.uniformLocation("u_normal_strength_bitangent"), bitangent_strength)

    texture = _SharedGLContext.texture
    texture.bind(0)
    glUniform1i(program.uniformLocation("u_texture"), 0)

    cap_texture = _SharedGLContext.cap_texture
    cap_texture.bind(1)
    glUniform1i(program.uniformLocation("u_cap_mask"), 1)

    vao = _SharedGLContext.vao
    vao.bind()
    glDrawElements(GL_TRIANGLES, idx.size, GL_UNSIGNED_INT, None)
    vao.release()
    cap_texture.release()
    texture.release()
    program.release()
    fbo.release()

    rgba_image = fbo.toImage(False)
    rgba_image = rgba_image.convertToFormat(QImage.Format_RGBA8888)
    rgba_ptr = rgba_image.bits()
    if not isinstance(rgba_ptr, memoryview):
        rgba_ptr = memoryview(rgba_ptr)
    rgba = np.frombuffer(rgba_ptr, dtype=np.uint8).reshape(
        (height, rgba_image.bytesPerLine() // 4, 4)
    )[:, :width, :].copy()

    alpha = rgba[:, :, 3] / 255.0
    if buf.shape[2] == 4:
        # FBO output is premultiplied RGBA; composite it over the existing
        # RGBA buffer. RGB is already scaled by src alpha, and the resulting
        # alpha follows the standard porter-duff over operator.
        buf[:, :, :3] = (
            rgba[:, :, :3]
            + buf[:, :, :3] * (1.0 - alpha[:, :, None])
        ).astype(np.uint8)
        buf[:, :, 3] = np.maximum(buf[:, :, 3], rgba[:, :, 3])
    elif buf.shape[2] == 3:
        buf[:] = (
            rgba[:, :, :3]
            + buf * (1.0 - alpha[:, :, None])
        ).astype(np.uint8)
    else:
        raise ValueError(f"Unsupported buffer channel count: {buf.shape[2]}")
