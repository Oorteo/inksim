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

out vec2 v_uv;
out vec3 v_tangent;
out vec3 v_bitangent;
out vec3 v_normal;
out vec3 v_color;

uniform mat4 u_transform;

void main() {
    v_uv = a_uv;
    v_tangent = a_tangent;
    v_bitangent = a_bitangent;
    v_normal = a_normal;
    v_color = a_color;
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

out vec4 fragColor;

uniform sampler2D u_texture;
uniform vec3 u_light_dir;
uniform float u_k_a;
uniform float u_k_d;
uniform float u_k_s;
uniform float u_specular_exponent;

void main() {
    vec4 texel = texture(u_texture, v_uv);
    if (texel.a < 0.01) {
        discard;
    }

    mat3 TBN = mat3(v_tangent, v_bitangent, v_normal);
    vec3 normal = normalize(TBN * (texel.rgb - 0.5));

    vec3 L = normalize(u_light_dir);
    vec3 V = vec3(0.0, 0.0, 1.0);
    vec3 H = normalize(L + V);

    float ndotl = max(dot(normal, L), 0.0);
    float diffuse = u_k_d * ndotl;
    float specular = u_k_s * pow(max(dot(normal, H), 0.0), u_specular_exponent);

    vec3 shaded = (u_k_a + diffuse) * v_color + vec3(specular);
    fragColor = vec4(clamp(shaded, 0.0, 1.0), texel.a);
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

    mx = (x1 + x2) / 2.0
    my = (y1 + y2) / 2.0

    us_x = x1 + across_x * h
    us_y = y1 + across_y * h
    um_x = mx + across_x * h
    um_y = my + across_y * h
    ue_x = x2 + across_x * h
    ue_y = y2 + across_y * h
    ls_x = x1 - across_x * h
    ls_y = y1 - across_y * h
    lm_x = mx - across_x * h
    lm_y = my - across_y * h
    le_x = x2 - across_x * h
    le_y = y2 - across_y * h

    # Texture repeats: constant twist density, no lower clamp (see above).
    repeats = length / stitch_height / thread_texture_aspect
    repeats = np.maximum(repeats, 1e-6)
    repeats[~valid] = 0.0
    cum = np.cumsum(repeats)
    texture_start = np.empty(n, dtype=np.float64)
    texture_start[0] = 0.0
    texture_start[1:] = cum[:-1]
    texture_start %= 1.0
    texture_mid = texture_start + repeats / 2.0
    texture_end = texture_start + repeats

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
    # color(3) = 16 floats. Six vertices per stitch: us, um, ue, ls, lm, le.
    verts = np.empty((n, 6, 16), dtype=np.float32)

    # positions
    verts[:, 0, 0] = us_x; verts[:, 0, 1] = us_y
    verts[:, 1, 0] = um_x; verts[:, 1, 1] = um_y
    verts[:, 2, 0] = ue_x; verts[:, 2, 1] = ue_y
    verts[:, 3, 0] = ls_x; verts[:, 3, 1] = ls_y
    verts[:, 4, 0] = lm_x; verts[:, 4, 1] = lm_y
    verts[:, 5, 0] = le_x; verts[:, 5, 1] = le_y

    # uv
    verts[:, 0, 2] = texture_start; verts[:, 0, 3] = 0.0
    verts[:, 1, 2] = texture_mid;   verts[:, 1, 3] = 0.0
    verts[:, 2, 2] = texture_end;   verts[:, 2, 3] = 0.0
    verts[:, 3, 2] = texture_start; verts[:, 3, 3] = 1.0
    verts[:, 4, 2] = texture_mid;   verts[:, 4, 3] = 1.0
    verts[:, 5, 2] = texture_end;   verts[:, 5, 3] = 1.0

    # tangent
    verts[:, 0, 4] = st_tx; verts[:, 0, 5] = st_ty; verts[:, 0, 6] = st_tz
    verts[:, 3, 4] = st_tx; verts[:, 3, 5] = st_ty; verts[:, 3, 6] = st_tz
    verts[:, 1, 4] = md_tx; verts[:, 1, 5] = md_ty; verts[:, 1, 6] = md_tz
    verts[:, 4, 4] = md_tx; verts[:, 4, 5] = md_ty; verts[:, 4, 6] = md_tz
    verts[:, 2, 4] = en_tx; verts[:, 2, 5] = en_ty; verts[:, 2, 6] = en_tz
    verts[:, 5, 4] = en_tx; verts[:, 5, 5] = en_ty; verts[:, 5, 6] = en_tz

    # bitangent (tilt-independent)
    for v in range(6):
        verts[:, v, 7] = bit_x
        verts[:, v, 8] = bit_y
        verts[:, v, 9] = bit_z

    # normal
    verts[:, 0, 10] = st_nx; verts[:, 0, 11] = st_ny; verts[:, 0, 12] = st_nz
    verts[:, 3, 10] = st_nx; verts[:, 3, 11] = st_ny; verts[:, 3, 12] = st_nz
    verts[:, 1, 10] = md_nx; verts[:, 1, 11] = md_ny; verts[:, 1, 12] = md_nz
    verts[:, 4, 10] = md_nx; verts[:, 4, 11] = md_ny; verts[:, 4, 12] = md_nz
    verts[:, 2, 10] = en_nx; verts[:, 2, 11] = en_ny; verts[:, 2, 12] = en_nz
    verts[:, 5, 10] = en_nx; verts[:, 5, 11] = en_ny; verts[:, 5, 12] = en_nz

    # color
    for v in range(6):
        verts[:, v, 13] = r
        verts[:, v, 14] = g
        verts[:, v, 15] = b

    verts = verts[valid].reshape(-1)

    # indices: 12 per stitch (two triangles per half-quad, four total)
    n_valid = int(valid.sum())
    base = np.arange(n_valid, dtype=np.uint32) * 6
    idx = np.empty((n_valid, 12), dtype=np.uint32)
    idx[:, 0] = base
    idx[:, 1] = base + 1
    idx[:, 2] = base + 3
    idx[:, 3] = base + 1
    idx[:, 4] = base + 3
    idx[:, 5] = base + 4
    idx[:, 6] = base + 1
    idx[:, 7] = base + 2
    idx[:, 8] = base + 4
    idx[:, 9] = base + 2
    idx[:, 10] = base + 4
    idx[:, 11] = base + 5
    idx = idx.reshape(-1)

    per_stitch = np.where(valid, 12, 0)
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
    stride = 16 * np.dtype(np.float32).itemsize
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

    fbo_format = QOpenGLFramebufferObjectFormat()
    fbo_format.setAttachment(QOpenGLFramebufferObject.CombinedDepthStencil)
    fbo_format.setInternalTextureFormat(GL_RGBA8)
    fbo_format.setMipmap(False)
    fbo = QOpenGLFramebufferObject(QSize(width, height), fbo_format)
    if not fbo.isValid():
        raise RuntimeError("Failed to create framebuffer object")
    _SharedGLContext.fbo = fbo

    glEnable(GL_BLEND)
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
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
    k_a = 0.2 + 0.2 * light_factor
    k_d = 0.6 + 0.3 * light_factor
    k_s = 0.4 + 0.3 * light_factor
    glUniform1f(program.uniformLocation("u_k_a"), k_a)
    glUniform1f(program.uniformLocation("u_k_d"), k_d)
    glUniform1f(program.uniformLocation("u_k_s"), k_s)
    glUniform1f(program.uniformLocation("u_specular_exponent"), 12.0)

    texture = _SharedGLContext.texture
    texture.bind(0)
    glUniform1i(program.uniformLocation("u_texture"), 0)

    vao = _SharedGLContext.vao
    vao.bind()
    glDrawElements(GL_TRIANGLES, idx.size, GL_UNSIGNED_INT, None)
    vao.release()
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
        # Blend RGB over existing RGBA buffer and mark covered pixels opaque.
        buf[:, :, :3] = (
            rgba[:, :, :3] * alpha[:, :, None]
            + buf[:, :, :3] * (1.0 - alpha[:, :, None])
        ).astype(np.uint8)
        buf[:, :, 3] = np.maximum(buf[:, :, 3], rgba[:, :, 3])
    elif buf.shape[2] == 3:
        buf[:] = (
            rgba[:, :, :3] * alpha[:, :, None]
            + buf * (1.0 - alpha[:, :, None])
        ).astype(np.uint8)
    else:
        raise ValueError(f"Unsupported buffer channel count: {buf.shape[2]}")
