"""OpenGL textured-quad stitch renderer for InkSim.

This renderer rasterises stitches as continuous textured ribbon quads
using a normal-map thread texture and Blinn-Phong lighting.  It renders
offscreen into an RGB buffer so it plugs into the existing viewport
pipeline without changing the viewer widget.
"""
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from PySide6.QtCore import QSize, Qt
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
    here = Path(__file__).resolve().parent
    candidate = here.parent / "assets" / "thread_textures" / "thread_3strands_normal.png"
    if candidate.exists():
        return candidate
    candidate = Path(__file__).resolve().parent.parent.parent.parent / "scripts" / "dev" / "gpu_prototype" / "texture" / "thread_textures_3" / "thread_3strands_normal.png"
    if candidate.exists():
        return candidate
    raise FileNotFoundError("Thread normal texture not found. Run texture generator first.")


_DEFAULT_TEXTURE_PATH = _default_texture_path()


def _load_texture(path: Path):
    img = Image.open(path).convert("RGBA")
    return np.array(img, dtype=np.uint8), img.width, img.height


def _build_satin_quads(
    stitches,
    visible_count,
    zoom,
    pan_x,
    pan_y,
    line_width,
    thread_texture_aspect=8.0,
    stitch_height_scale=4.0,
):
    """Convert stitch segments into textured quad vertex data."""
    vertices = []
    indices = []
    cur_index = 0
    thread_position = 0.0

    for i in range(visible_count):
        x1 = float(stitches[i, 0]) * zoom + pan_x
        y1 = float(stitches[i, 1]) * zoom + pan_y
        x2 = float(stitches[i, 2]) * zoom + pan_x
        y2 = float(stitches[i, 3]) * zoom + pan_y
        r = float(stitches[i, 4]) / 255.0
        g = float(stitches[i, 5]) / 255.0
        b = float(stitches[i, 6]) / 255.0

        dx = x2 - x1
        dy = y2 - y1
        length = math.hypot(dx, dy)
        if length < 1e-6:
            continue
        along = np.array([dx / length, dy / length], dtype=np.float32)
        across = np.array([-along[1], along[0]], dtype=np.float32)

        stitch_height = max(1.0, line_width * zoom * stitch_height_scale * 0.5)

        us = np.array([x1, y1]) + across * (stitch_height / 2)
        um = (np.array([x1, y1]) + np.array([x2, y2])) / 2.0 + across * (stitch_height / 2)
        ue = np.array([x2, y2]) + across * (stitch_height / 2)
        ls = np.array([x1, y1]) - across * (stitch_height / 2)
        lm = (np.array([x1, y1]) + np.array([x2, y2])) / 2.0 - across * (stitch_height / 2)
        le = np.array([x2, y2]) - across * (stitch_height / 2)

        theta = -math.atan2(along[1], along[0])
        ct = math.cos(theta)
        st = math.sin(theta)

        def make_tbn(tilt_deg):
            rad = math.radians(tilt_deg)
            sn = math.sin(rad)
            cn = math.cos(rad)
            tx = cn * ct
            ty = cn * st
            tz = sn
            nx = -sn * ct
            ny = -sn * st
            nz = cn
            tangent = np.array([tx, ty, tz], dtype=np.float32)
            normal = np.array([nx, ny, nz], dtype=np.float32)
            bitangent = np.cross(normal, tangent)
            return tangent, bitangent, normal

        start_t, start_b, start_n = make_tbn(60)
        mid_t, mid_b, mid_n = make_tbn(0)
        end_t, end_b, end_n = make_tbn(-60)

        repeats = max(1.0, length / stitch_height / thread_texture_aspect)
        texture_start = thread_position
        texture_mid = thread_position + repeats / 2.0
        texture_end = thread_position + repeats
        thread_position = texture_end % 1.0

        color = (float(r), float(g), float(b))

        def add_vert(pos, u, v, t, b, n, col):
            vertices.extend([
                float(pos[0]), float(pos[1]),
                float(u), float(v),
                float(t[0]), float(t[1]), float(t[2]),
                float(b[0]), float(b[1]), float(b[2]),
                float(n[0]), float(n[1]), float(n[2]),
                col[0], col[1], col[2],
            ])

        add_vert(us, texture_start, 0.0, start_t, start_b, start_n, color)
        add_vert(um, texture_mid, 0.0, mid_t, mid_b, mid_n, color)
        add_vert(ue, texture_end, 0.0, end_t, end_b, end_n, color)
        add_vert(ls, texture_start, 1.0, start_t, start_b, start_n, color)
        add_vert(lm, texture_mid, 1.0, mid_t, mid_b, mid_n, color)
        add_vert(le, texture_end, 1.0, end_t, end_b, end_n, color)

        indices.extend([
            cur_index,     cur_index + 1, cur_index + 3,
            cur_index + 1, cur_index + 3, cur_index + 4,
            cur_index + 1, cur_index + 2, cur_index + 4,
            cur_index + 2, cur_index + 4, cur_index + 5,
        ])
        cur_index += 6

    return np.array(vertices, dtype=np.float32), np.array(indices, dtype=np.uint32)


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
    glEnable(GL_DEPTH_TEST)

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

    verts, idx = _build_satin_quads(
        stitches,
        visible_count,
        zoom,
        pan_x,
        pan_y,
        line_width,
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
