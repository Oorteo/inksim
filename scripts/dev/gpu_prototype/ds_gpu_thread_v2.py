#!/usr/bin/env uvr

"""
Simple GPU prototype using textured quad strips + normal map,
following the approach from opengl-render/lib/gui/experimental/gl_renderer.py.
"""
import sys
import math
import numpy as np
from pathlib import Path
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QMouseEvent, QSurfaceFormat
from PySide6.QtOpenGL import (
    QOpenGLBuffer,
    QOpenGLShader,
    QOpenGLShaderProgram,
    QOpenGLVertexArrayObject,
    QOpenGLTexture,
)
from PySide6.QtOpenGLWidgets import QOpenGLWidget
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
uniform int u_debug_mode; // 0 = shaded, 1 = raw texture, 2 = UV debug

void main() {
    if (u_debug_mode == 1) {
        // Show raw texture 1:1 (no lighting, no TBN).
        vec4 t = texture(u_texture, v_uv);
        fragColor = vec4(t.rgb, 1.0);
        return;
    }
    if (u_debug_mode == 2) {
        // UV debug: red = u, green = v.
        fragColor = vec4(v_uv, 0.0, 1.0);
        return;
    }

    vec4 texel = texture(u_texture, v_uv);
    // texel.a is the thread mask; alpha blend instead of discard for smooth edges.
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


def load_texture(path: str):
    img = Image.open(path).convert("RGBA")
    data = np.array(img, dtype=np.uint8)
    return data, img.width, img.height


def build_satin_stitches(rows=14, width_mm=30.0, height_mm=10.0,
                         color=(180.0, 20.0, 40.0), thickness=0.35,
                         thread_texture_aspect=8.0):
    """Build stitch data for a satin patch. Returns (vertices, indices)."""
    stitch_height = thickness * 4.0  # visual width of the thread strip
    vertices = []
    indices = []
    cur_index = 0
    thread_position = 0.0
    color_norm = [c / 255.0 for c in color]

    step_x = width_mm / rows
    for i in range(rows):
        x = -width_mm / 2.0 + i * step_x + step_x / 2
        p1 = np.array([x, -height_mm / 2.0], dtype=np.float32)
        p2 = np.array([x, height_mm / 2.0], dtype=np.float32)

        delta = p2 - p1
        length = np.linalg.norm(delta)
        if length < 1e-6:
            continue
        along = delta / length
        across = np.array([-along[1], along[0]], dtype=np.float32)

        # Six vertices for one stitch quad strip (two triangles).
        us = p1 + across * (stitch_height / 2)
        um = (p1 + p2) / 2 + across * (stitch_height / 2)
        ue = p2 + across * (stitch_height / 2)
        ls = p1 - across * (stitch_height / 2)
        lm = (p1 + p2) / 2 - across * (stitch_height / 2)
        le = p2 - across * (stitch_height / 2)

        theta = -math.atan2(along[1], along[0])
        ct = math.cos(theta)
        st = math.sin(theta)

        # TBN: tangent along stitch, bitangent across, normal out of screen.
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

        repeats = length / stitch_height / thread_texture_aspect
        texture_start = thread_position
        texture_mid = thread_position + repeats / 2
        texture_end = thread_position + repeats
        thread_position = texture_end % 1.0

        def add_vert(pos, u, v, t, b, n):
            vertices.extend([
                pos[0], pos[1],
                u, v,
                t[0], t[1], t[2],
                b[0], b[1], b[2],
                n[0], n[1], n[2],
                color_norm[0], color_norm[1], color_norm[2],
            ])

        add_vert(us, texture_start, 0.0, start_t, start_b, start_n)
        add_vert(um, texture_mid,   0.0, mid_t,   mid_b,   mid_n)
        add_vert(ue, texture_end,   0.0, end_t,   end_b,   end_n)
        add_vert(ls, texture_start, 1.0, start_t, start_b, start_n)
        add_vert(lm, texture_mid,   1.0, mid_t,   mid_b,   mid_n)
        add_vert(le, texture_end,   1.0, end_t,   end_b,   end_n)

        indices.extend([
            cur_index,     cur_index + 1, cur_index + 3,
            cur_index + 1, cur_index + 3, cur_index + 4,
            cur_index + 1, cur_index + 2, cur_index + 4,
            cur_index + 2, cur_index + 4, cur_index + 5,
        ])
        cur_index += 6

    return np.array(vertices, dtype=np.float32), np.array(indices, dtype=np.uint32)


class StitchGLWidget(QOpenGLWidget):
    def __init__(self, texture_path: str, parent=None):
        super().__init__(parent)
        self._texture_path = texture_path
        self._program = None
        self._vao = None
        self._vbo = None
        self._ibo = None
        self._texture = None
        self._zoom = 15.0
        self._pan = np.array([0.0, 0.0], dtype=np.float32)
        self._dragging = False
        self._last_mouse = np.array([0.0, 0.0], dtype=np.float32)
        self._debug_mode = 0

    def initializeGL(self):
        print("=== INITIALIZEGL ===")
        fmt = self.context().format()
        print(f"OpenGL version: {fmt.majorVersion()}.{fmt.minorVersion()}")

        self._program = QOpenGLShaderProgram(self)
        self._program.addShaderFromSourceCode(QOpenGLShader.Vertex, VERTEX_SHADER)
        self._program.addShaderFromSourceCode(QOpenGLShader.Fragment, FRAGMENT_SHADER)
        if not self._program.link():
            print("Shader link failed:", self._program.log())
            return
        print("Shader program linked successfully")

        verts, idx = build_satin_stitches(rows=28, color=(200.0, 20.0, 30.0))
        self._index_count = idx.size

        self._vbo = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        self._vbo.create()
        self._vbo.bind()
        self._vbo.allocate(verts.tobytes(), verts.nbytes)
        self._vbo.release()

        self._ibo = QOpenGLBuffer(QOpenGLBuffer.IndexBuffer)
        self._ibo.create()
        self._ibo.bind()
        self._ibo.allocate(idx.tobytes(), idx.nbytes)
        self._ibo.release()

        self._vao = QOpenGLVertexArrayObject()
        self._vao.create()
        self._vao.bind()
        self._vbo.bind()
        self._ibo.bind()

        stride = 16 * verts.itemsize
        offset = 0
        self._program.enableAttributeArray(0)
        self._program.setAttributeBuffer(0, GL_FLOAT, offset, 2, stride)
        offset += 2 * verts.itemsize
        self._program.enableAttributeArray(1)
        self._program.setAttributeBuffer(1, GL_FLOAT, offset, 2, stride)
        offset += 2 * verts.itemsize
        self._program.enableAttributeArray(2)
        self._program.setAttributeBuffer(2, GL_FLOAT, offset, 3, stride)
        offset += 3 * verts.itemsize
        self._program.enableAttributeArray(3)
        self._program.setAttributeBuffer(3, GL_FLOAT, offset, 3, stride)
        offset += 3 * verts.itemsize
        self._program.enableAttributeArray(4)
        self._program.setAttributeBuffer(4, GL_FLOAT, offset, 3, stride)
        offset += 3 * verts.itemsize
        self._program.enableAttributeArray(5)
        self._program.setAttributeBuffer(5, GL_FLOAT, offset, 3, stride)

        self._vao.release()
        self._ibo.release()
        self._vbo.release()

        tex_data, tex_w, tex_h = load_texture(self._texture_path)
        self._texture = QOpenGLTexture(QOpenGLTexture.Target2D)
        self._texture.create()
        self._texture.setFormat(QOpenGLTexture.RGBAFormat)
        self._texture.setSize(tex_w, tex_h)
        self._texture.allocateStorage()
        self._texture.setData(
            QOpenGLTexture.RGBA,
            QOpenGLTexture.UInt8,
            tex_data.tobytes(),
        )
        self._texture.setMinificationFilter(QOpenGLTexture.LinearMipMapLinear)
        self._texture.setMagnificationFilter(QOpenGLTexture.Linear)
        self._texture.setWrapMode(QOpenGLTexture.DirectionS, QOpenGLTexture.Repeat)
        self._texture.setWrapMode(QOpenGLTexture.DirectionT, QOpenGLTexture.ClampToEdge)
        self._texture.generateMipMaps()

        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

        print("=== INITIALIZEGL DONE ===")

    def paintGL(self):
        if self._program is None or not self._program.isLinked():
            return

        self.context().functions().glClearColor(0.0, 0.0, 0.0, 1.0)
        self.context().functions().glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

        w = self.width()
        h = self.height()

        # Build column-major ortho matrix: translate(pan) * scale(zoom) * ortho.
        # Pan is in screen pixels; convert to NDC directly so 1 px mouse = 1 px image.
        sx = self._zoom * 2.0 / w
        sy = self._zoom * 2.0 / h
        tx = self._pan[0] * 2.0 / w
        ty = -self._pan[1] * 2.0 / h  # invert Qt y so panning feels natural

        transform = np.array([
            sx, 0.0, 0.0, 0.0,
            0.0, sy, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            tx, ty, 0.0, 1.0,
        ], dtype=np.float32)

        self._program.bind()
        loc = self._program.uniformLocation("u_transform")
        glUniformMatrix4fv(loc, 1, GL_FALSE, transform)

        glUniform3f(self._program.uniformLocation("u_light_dir"), -0.4, -0.4, 0.82)
        glUniform1f(self._program.uniformLocation("u_k_a"), 0.2)
        glUniform1f(self._program.uniformLocation("u_k_d"), 0.8)
        glUniform1f(self._program.uniformLocation("u_k_s"), 0.5)
        glUniform1f(self._program.uniformLocation("u_specular_exponent"), 10.0)

        self._texture.bind(0)
        glUniform1i(self._program.uniformLocation("u_texture"), 0)
        glUniform1i(self._program.uniformLocation("u_debug_mode"), self._debug_mode)

        self._vao.bind()
        glDrawElements(GL_TRIANGLES, self._index_count, GL_UNSIGNED_INT, None)
        self._vao.release()
        self._texture.release()
        self._program.release()

    def resizeGL(self, w, h):
        glViewport(0, 0, w, h)

    def _mouse_pos(self, event: QMouseEvent):
        pos = np.array([event.position().x(), event.position().y()], dtype=np.float32)
        return pos

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._last_mouse = self._mouse_pos(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._dragging:
            pos = self._mouse_pos(event)
            delta = pos - self._last_mouse
            self._pan += delta
            self._last_mouse = pos
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False

    def wheelEvent(self, event):
        # Zoom around mouse position would be nicer; simple version here.
        delta = event.angleDelta().y()
        factor = 1.1 if delta > 0 else 0.9
        self._zoom *= factor
        self.update()

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_1:
            self._debug_mode = 0
            print("Debug: shaded mode")
        elif key == Qt.Key.Key_2:
            self._debug_mode = 1
            print("Debug: raw texture mode")
        elif key == Qt.Key.Key_3:
            self._debug_mode = 2
            print("Debug: UV mode")
        self.update()


if __name__ == "__main__":
    app = QApplication(sys.argv)

    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    QSurfaceFormat.setDefaultFormat(fmt)

    texture_path = str(Path(__file__).resolve().parent / "texture" / "thread_textures_3" / "thread_3strands_normal.png")
    widget = StitchGLWidget(texture_path)
    widget.resize(900, 700)
    widget.show()
    print("=== Textured-quad GPU prototype started ===")
    sys.exit(app.exec())
