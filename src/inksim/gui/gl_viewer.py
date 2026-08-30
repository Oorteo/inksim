"""OpenGL-based stitch viewer widget for InkSim.

This widget renders stitches as textured thread quads directly to the
screen using the same GPU pipeline as the offscreen export renderer.
It is used when the active stitch renderer is "gpu_textured".
"""
import math
from pathlib import Path

import numpy as np
from PIL import Image
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtOpenGL import (
    QOpenGLBuffer,
    QOpenGLFramebufferObject,
    QOpenGLFramebufferObjectFormat,
    QOpenGLShader,
    QOpenGLShaderProgram,
    QOpenGLTexture,
    QOpenGLVertexArrayObject,
)
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QApplication
from OpenGL.GL import *

from ..render.stitches_gl import _build_satin_quads as build_satin_quads
from ..render.stitches_gl import _default_texture_path

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
uniform int u_debug_mode; // 0 = shaded, 1 = raw texture, 2 = UV

void main() {
    vec4 texel = texture(u_texture, v_uv);
    if (texel.a < 0.01) {
        discard;
    }

    if (u_debug_mode == 1) {
        fragColor = vec4(texel.rgb, 1.0);
        return;
    }
    if (u_debug_mode == 2) {
        fragColor = vec4(v_uv, 0.0, 1.0);
        return;
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


def _load_texture(path: Path):
    img = Image.open(path).convert("RGBA")
    return np.array(img, dtype=np.uint8), img.width, img.height


def list_thread_textures():
    """Return ``[(label, path)]`` of available thread normal/mask textures.

    Includes the packaged asset(s) under ``assets/thread_textures/`` and, for
    development, the regenerated previews under ``scripts/texture/renders/``.
    """
    results = []
    here = Path(__file__).resolve().parent
    assets_dir = here.parent / "assets" / "thread_textures"
    if assets_dir.exists():
        for p in sorted(assets_dir.glob("*_normal_mask.png")):
            results.append((p.stem, p))
    scripts_dir = here.parent.parent.parent / "scripts" / "texture" / "renders"
    if scripts_dir.exists():
        for p in sorted(scripts_dir.glob("*/*_normal_mask.png")):
            results.append((f"{p.parent.name}/{p.stem}", p))
    return results


class GLStitchWidget(QOpenGLWidget):
    """OpenGL widget that renders textured stitch quads.

    Attributes mirror the bitmap viewer so the parent EmbroideryViewerWidget
    can switch between raster and OpenGL rendering modes.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        # Mouse/keyboard input is handled entirely by the parent viewer (pan,
        # zoom, stitch stepping, needle, timeline...); this widget is only a
        # display surface, so let all mouse events pass through to it.
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._program = None
        self._vao = None
        self._vbo = None
        self._ibo = None
        self._texture = None
        self._texture_path = None
        self._zoom = 1.0
        self._pan = np.array([0.0, 0.0], dtype=np.float32)
        self._bg_color = (0.0, 0.0, 0.0)
        self._light_factor = 0.45
        self._stitches = np.zeros((0, 7), dtype=np.float32)
        self._visible_count = 0
        self._line_width = 0.4
        self._debug_mode = 0  # 0=shaded, 1=raw texture, 2=UV (for debugging visibility)
        self._needs_upload = True
        self._verts = np.zeros((0,), dtype=np.float32)
        self._idx = np.zeros((0,), dtype=np.uint32)
        self._index_counts = np.zeros((0,), dtype=np.int64)
        self._draw_count = 0

    def set_view(self, zoom, pan_x, pan_y):
        self._zoom = zoom
        self._pan = np.array([pan_x, pan_y], dtype=np.float32)
        self.update()

    def set_background(self, r, g, b):
        self._bg_color = (r / 255.0, g / 255.0, b / 255.0)
        self.update()

    def set_light_factor(self, light_factor):
        self._light_factor = light_factor
        self.update()

    def set_stitches(self, stitches, line_width):
        """Set the full stitch array; geometry is (re)built for all of it.

        Use `set_visible_count` to change how many stitches are drawn --
        that never requires rebuilding geometry, so playback/timeline/key
        stepping stays cheap.
        """
        if stitches is self._stitches and line_width == self._line_width:
            return
        self._stitches = stitches
        self._line_width = line_width
        self._needs_upload = True
        self.update()

    def set_visible_count(self, visible_count):
        self._visible_count = visible_count
        self.update()

    def initializeGL(self):
        fmt = self.context().format()
        print(f"[GLStitchWidget] OpenGL {fmt.majorVersion()}.{fmt.minorVersion()}")

        self._program = QOpenGLShaderProgram(self)
        self._program.addShaderFromSourceCode(QOpenGLShader.Vertex, VERTEX_SHADER)
        self._program.addShaderFromSourceCode(QOpenGLShader.Fragment, FRAGMENT_SHADER)
        if not self._program.link():
            print("Shader link failed:", self._program.log())
            return

        self._vao = QOpenGLVertexArrayObject()
        self._vao.create()

        self._vbo = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        self._vbo.create()
        self._ibo = QOpenGLBuffer(QOpenGLBuffer.IndexBuffer)
        self._ibo.create()

        self._configure_vao()

        self._load_texture(self._texture_path or _default_texture_path())

        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        # All quads share z=0 -- stitch layering must follow draw order (later
        # stitch on top), not the depth buffer, so depth testing stays off.
        glDisable(GL_DEPTH_TEST)

    def _load_texture(self, path):
        """(Re)create the thread texture from *path* (a normal/mask PNG)."""
        tex_data, tex_w, tex_h = _load_texture(path)
        if self._texture is not None:
            self._texture.destroy()
        self._texture = QOpenGLTexture(QOpenGLTexture.Target2D)
        self._texture.create()
        self._texture.setFormat(QOpenGLTexture.RGBAFormat)
        self._texture.setSize(tex_w, tex_h)
        self._texture.allocateStorage()
        self._texture.setData(QOpenGLTexture.RGBA, QOpenGLTexture.UInt8, tex_data.tobytes())
        self._texture.setMinificationFilter(QOpenGLTexture.LinearMipMapLinear)
        self._texture.setMagnificationFilter(QOpenGLTexture.Linear)
        self._texture.setWrapMode(QOpenGLTexture.DirectionS, QOpenGLTexture.Repeat)
        self._texture.setWrapMode(QOpenGLTexture.DirectionT, QOpenGLTexture.ClampToEdge)
        self._texture.generateMipMaps()
        self._texture_path = path

    def set_texture_path(self, path):
        """Swap the thread texture at runtime (e.g. from a context menu)."""
        if self._texture is None:
            # GL context not initialised yet; remember the path for later.
            self._texture_path = path
            return
        self.makeCurrent()
        self._load_texture(path)
        self.doneCurrent()
        self.update()

    def _configure_vao(self):
        self._vao.bind()
        self._vbo.bind()
        self._ibo.bind()
        stride = 16 * np.dtype(np.float32).itemsize
        offset = 0
        self._program.enableAttributeArray(0)
        self._program.setAttributeBuffer(0, GL_FLOAT, offset, 2, stride)
        offset += 2 * np.dtype(np.float32).itemsize
        self._program.enableAttributeArray(1)
        self._program.setAttributeBuffer(1, GL_FLOAT, offset, 2, stride)
        offset += 2 * np.dtype(np.float32).itemsize
        self._program.enableAttributeArray(2)
        self._program.setAttributeBuffer(2, GL_FLOAT, offset, 3, stride)
        offset += 3 * np.dtype(np.float32).itemsize
        self._program.enableAttributeArray(3)
        self._program.setAttributeBuffer(3, GL_FLOAT, offset, 3, stride)
        offset += 3 * np.dtype(np.float32).itemsize
        self._program.enableAttributeArray(4)
        self._program.setAttributeBuffer(4, GL_FLOAT, offset, 3, stride)
        offset += 3 * np.dtype(np.float32).itemsize
        self._program.enableAttributeArray(5)
        self._program.setAttributeBuffer(5, GL_FLOAT, offset, 3, stride)
        self._vao.release()
        self._ibo.release()
        self._vbo.release()

    def _upload_geometry(self):
        if not self._needs_upload or self._stitches.shape[0] == 0:
            return
        # Build geometry once in model space (zoom=1, pan=0) for ALL stitches;
        # zoom/pan are applied per-frame via u_transform, and the visible
        # sub-range is applied via index_counts, so neither ever re-runs this
        # (slow, pure-Python) quad builder.
        verts, idx, index_counts = build_satin_quads(
            self._stitches,
            self._stitches.shape[0],
            1.0,
            0.0,
            0.0,
            self._line_width,
        )
        self._verts = verts
        self._idx = idx
        self._index_counts = index_counts

        self._vbo.bind()
        if verts.nbytes > self._vbo.size():
            self._vbo.allocate(verts.tobytes(), verts.nbytes)
        else:
            self._vbo.write(0, verts.tobytes(), verts.nbytes)
        self._vbo.release()

        self._ibo.bind()
        if idx.nbytes > self._ibo.size():
            self._ibo.allocate(idx.tobytes(), idx.nbytes)
        else:
            self._ibo.write(0, idx.tobytes(), idx.nbytes)
        self._ibo.release()
        self._needs_upload = False

    def paintGL(self):
        if self._program is None or not self._program.isLinked():
            return

        self._upload_geometry()

        glClearColor(*self._bg_color, 1.0)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

        count = min(self._visible_count, self._index_counts.shape[0])
        draw_count = int(self._index_counts[count - 1]) if count > 0 else 0
        if draw_count == 0:
            return

        w = self.width()
        h = self.height()
        # Vertices are in model space (see _upload_geometry). This matrix is the
        # only place zoom/pan is applied: model -> pixel (y-down, matches the
        # raster viewer convention) -> NDC.
        sx = self._zoom * 2.0 / w
        sy = -self._zoom * 2.0 / h
        tx = self._pan[0] * 2.0 / w - 1.0
        ty = 1.0 - self._pan[1] * 2.0 / h

        transform = np.array([
            sx, 0.0, 0.0, 0.0,
            0.0, sy, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            tx, ty, 0.0, 1.0,
        ], dtype=np.float32)

        self._program.bind()
        glUniformMatrix4fv(self._program.uniformLocation("u_transform"), 1, GL_FALSE, transform)
        glUniform3f(self._program.uniformLocation("u_light_dir"), -0.4, -0.4, 0.82)
        k_a = 0.2 + 0.2 * self._light_factor
        k_d = 0.6 + 0.3 * self._light_factor
        k_s = 0.4 + 0.3 * self._light_factor
        glUniform1f(self._program.uniformLocation("u_k_a"), k_a)
        glUniform1f(self._program.uniformLocation("u_k_d"), k_d)
        glUniform1f(self._program.uniformLocation("u_k_s"), k_s)
        glUniform1f(self._program.uniformLocation("u_specular_exponent"), 12.0)
        glUniform1i(self._program.uniformLocation("u_debug_mode"), self._debug_mode)

        self._texture.bind(0)
        glUniform1i(self._program.uniformLocation("u_texture"), 0)

        self._vao.bind()
        glDrawElements(GL_TRIANGLES, draw_count, GL_UNSIGNED_INT, None)
        self._vao.release()
        self._texture.release()
        self._program.release()

    def resizeGL(self, w, h):
        glViewport(0, 0, w, h)
