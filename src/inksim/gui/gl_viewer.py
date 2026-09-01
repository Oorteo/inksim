# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

"""OpenGL-based stitch viewer widget for InkSim.

This widget renders stitches as textured thread quads directly to the
screen using the same GPU pipeline as the offscreen export renderer.
It is used when the active stitch renderer is "gpu_textured".
"""
import math
from pathlib import Path

import numpy as np
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QSurfaceFormat
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

from ..constants import DENSITY_CRITICAL_PER_MM2, DENSITY_WARNING_PER_MM2
from ..debug import is_enabled, logger
from ..render.stitches_gl import _build_satin_quads as build_satin_quads
from ..render.stitches_gl import (
    _default_texture_path,
    _lighting_coefficients,
    _load_texture,
    _normal_strengths,
    texture_width_fraction,
    texture_cap_radius_fraction,
)

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
uniform int u_debug_mode; // 0 = shaded, 1 = raw texture, 2 = UV

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

    if (u_debug_mode == 1) {
        fragColor = vec4(texel.rgb, 1.0);
        return;
    }
    if (u_debug_mode == 2) {
        fragColor = vec4(v_uv, 0.0, 1.0);
        return;
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
    // Premultiplied alpha: edge/cap pixels must not emit full lighting,
    // otherwise the thread looks dilated by a bright fringe.
    fragColor = vec4(clamp(shaded, 0.0, 1.0) * alpha, alpha);
}
"""

# Full-screen triangle that reconstructs world (mm) coordinates per fragment,
# used to draw the measurement grid in the background (under the stitches).
GRID_VERTEX_SHADER = """
#version 330 core
uniform vec2 u_viewport;
uniform vec2 u_pan;
uniform float u_zoom;
out vec2 v_world;
void main() {
    vec2 pos = vec2(float((gl_VertexID << 1) & 2), float(gl_VertexID & 2));
    // pos is in NDC [0,1] (Y up). Convert to pixel space (Y down) to match
    // the pan convention used by the stitch renderer.
    vec2 screen = vec2(pos.x * u_viewport.x, (1.0 - pos.y) * u_viewport.y);
    v_world = (screen - u_pan) / u_zoom;
    gl_Position = vec4(pos * 2.0 - 1.0, 0.0, 1.0);
}
"""

GRID_FRAGMENT_SHADER = """
#version 330 core
in vec2 v_world;
out vec4 fragColor;
uniform vec3 u_bg_color;
uniform float u_zoom;
uniform float u_zoom_ratio;

float gridLine(float coord, float spacing) {
    float d = abs(fract(coord / spacing - 0.5) - 0.5) * spacing;
    float w = fwidth(coord) * 1.5;
    return 1.0 - smoothstep(0.0, w, d);
}

void main() {
    vec3 color = u_bg_color;
    float lum = dot(u_bg_color, vec3(0.299, 0.587, 0.114));

    // 1 mm fine grid fades in from 1.5x real size (u_zoom_ratio is the
    // relative zoom, 1.0 == physical 1:1).
    float fine = max(gridLine(v_world.x, 1.0), gridLine(v_world.y, 1.0));
    float fineFade = smoothstep(1.5, 3.0, u_zoom_ratio);

    // 0.1 mm micro grid for fine thread-width tuning at high zoom.
    float micro = max(gridLine(v_world.x, 0.1), gridLine(v_world.y, 0.1));
    float microFade = smoothstep(1.0, 2.0, u_zoom_ratio);

    float minor = max(gridLine(v_world.x, 10.0), gridLine(v_world.y, 10.0));
    float major = max(gridLine(v_world.x, 50.0), gridLine(v_world.y, 50.0));
    float ax = 1.0 - smoothstep(0.0, fwidth(v_world.x) * 1.5, abs(v_world.x));
    float ay = 1.0 - smoothstep(0.0, fwidth(v_world.y) * 1.5, abs(v_world.y));

    vec3 lineColor = lum > 0.5 ? vec3(0.0) : vec3(1.0);
    vec3 axisXColor = vec3(0.8, 0.4, 0.4);
    vec3 axisYColor = vec3(0.4, 0.8, 0.4);

    color = mix(color, lineColor, micro * 0.10 * microFade);
    color = mix(color, lineColor, fine * 0.15 * fineFade);
    color = mix(color, lineColor, minor * 0.18);
    color = mix(color, lineColor, major * 0.30);
    color = mix(color, axisXColor, ax * 0.5);
    color = mix(color, axisYColor, ay * 0.5);

    fragColor = vec4(color, 1.0);
}
"""

# Point shader for the density overlay (needle-puncture dots).
DENSITY_VERTEX_SHADER = """
#version 330 core
layout(location = 0) in vec2 a_pos;      // world (mm) position
layout(location = 1) in vec3 a_color;    // marker color
layout(location = 2) in float a_radius;  // marker radius in world mm
layout(location = 3) in float a_repeated; // 1.0 = zero-length stitch (ring)
uniform mat4 u_transform;
uniform float u_zoom;
out vec3 v_color;
out float v_repeated;
void main() {
    v_color = a_color;
    v_repeated = a_repeated;
    gl_Position = u_transform * vec4(a_pos, 0.0, 1.0);
    gl_PointSize = max(1.0, a_radius * u_zoom * 2.0);
}
"""

DENSITY_FRAGMENT_SHADER = """
#version 330 core
in vec3 v_color;
in float v_repeated;
out vec4 fragColor;
void main() {
    // gl_PointCoord is [0,1] across the point; center it.
    vec2 p = gl_PointCoord - 0.5;
    float r = length(p);
    if (r > 0.5) {
        discard;
    }
    if (v_repeated > 0.5) {
        // Zero-length stitch: red ring (matches the CPU renderer).
        float ring = smoothstep(0.30, 0.42, r) * (1.0 - smoothstep(0.42, 0.5, r));
        if (ring < 0.01) {
            discard;
        }
        fragColor = vec4(0.92, 0.14, 0.14, 1.0);
        return;
    }
    // Darker center (needle puncture).
    vec3 col = mix(vec3(0.04, 0.04, 0.04), v_color, smoothstep(0.0, 0.5, r));
    fragColor = vec4(col, 1.0);
}
"""

def list_thread_textures():
    """Return ``[(label, path)]`` of available thread normal/mask textures.

    Only the packaged assets under ``assets/thread_textures/`` are listed;
    these are the textures actually shipped in the wheel and loaded at runtime.
    The dev-only previews under ``scripts/texture/renders/`` are intentionally
    omitted from the menu.
    """
    results = []
    here = Path(__file__).resolve().parent
    assets_dir = here.parent / "assets" / "thread_textures"
    if assets_dir.exists():
        for p in sorted(assets_dir.glob("*_normal_mask.png")):
            results.append((p.stem, p))
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
        self._viewer = parent
        self._program = None
        self._vao = None
        self._vbo = None
        self._ibo = None
        self._texture = None
        self._cap_texture = None
        self._texture_path = None
        self._width_fraction = 1.0
        self._cap_fraction = 0.0
        self._zoom = 1.0
        self._zoom_ratio = 1.0
        self._pan = np.array([0.0, 0.0], dtype=np.float32)
        self._bg_color = (0.0, 0.0, 0.0)
        self._dark_factor = 0.5
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
        # Overlay state (mirrors the parent viewer's analysis overlays).
        self._show_jumps = False
        self._risky_jumps_only = False
        self._jump_segments = []
        self._show_density = False
        self._density_points = np.zeros((0, 2), dtype=np.float32)
        self._density_values = np.zeros((0,), dtype=np.float32)
        self._density_repeated = np.zeros((0,), dtype=np.bool_)
        self._show_needle = True
        self._needle_pos = np.array([0.0, 0.0], dtype=np.float32)
        self._needle_color = (255, 255, 255)
        self._needle_radius = 30.0
        self._needle_width = 1.0
        self._needle_fullscreen = False
        self._needle_pulse = 0.0
        self._show_stitches = True
        self._show_grid = True

    def set_view(self, zoom, pan_x, pan_y, zoom_ratio=1.0):
        self._zoom = zoom
        self._zoom_ratio = zoom_ratio
        self._pan = np.array([pan_x, pan_y], dtype=np.float32)
        self.update()

    def cleanup(self):
        """Release OpenGL resources while the context is still current.

        QOpenGLTexture/QOpenGLBuffer objects must be destroyed with a current
        context, otherwise Qt prints warnings about textures not being
        destroyed. Call this before the widget is hidden/destroyed.
        """
        if getattr(self, "_cleaned_up", False):
            return
        self._cleaned_up = True
        if not self.context():
            return
        if not self.context().isValid():
            return
        self.makeCurrent()
        if self._texture is not None:
            self._texture.destroy()
            self._texture = None
        if self._cap_texture is not None:
            self._cap_texture.destroy()
            self._cap_texture = None
        if self._ibo is not None:
            self._ibo.destroy()
            self._ibo = None
        if self._vbo is not None:
            self._vbo.destroy()
            self._vbo = None
        if self._vao is not None:
            self._vao.destroy()
            self._vao = None
        if self._program is not None:
            self._program.removeAllShaders()
            self._program = None
        if self._density_vbo is not None:
            self._density_vbo.destroy()
            self._density_vbo = None
        if self._density_vao is not None:
            self._density_vao.destroy()
            self._density_vao = None
        if self._density_program is not None:
            self._density_program.removeAllShaders()
            self._density_program = None
        if self._grid_program is not None:
            self._grid_program.removeAllShaders()
            self._grid_program = None
        self.doneCurrent()

    def set_background(self, r, g, b):
        self._bg_color = (r / 255.0, g / 255.0, b / 255.0)
        self.update()

    def set_light_factor(self, light_factor):
        self._light_factor = light_factor
        self.update()

    def set_dark_factor(self, dark_factor):
        self._dark_factor = dark_factor
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

    def invalidate_geometry(self):
        """Force a rebuild of the stitch quad geometry on the next paint.

        Call this after the parent viewer mutates stitch coordinates in
        place (e.g. rotate) so the GPU renderer uploads fresh vertices.
        """
        self._needs_upload = True
        self.update()

    def set_visible_count(self, visible_count):
        self._visible_count = visible_count
        self.update()

    def set_jumps(self, show_jumps, risky_only, jump_segments):
        self._show_jumps = show_jumps
        self._risky_jumps_only = risky_only
        self._jump_segments = jump_segments
        self.update()

    def set_density(self, show_density, points, values, repeated):
        self._show_density = show_density
        self._density_points = points
        self._density_values = values
        self._density_repeated = repeated
        self.update()

    def set_needle(self, show_needle, world_x, world_y, color, radius, width, fullscreen, pulse):
        self._show_needle = show_needle
        self._needle_pos = np.array([world_x, world_y], dtype=np.float32)
        self._needle_color = color
        self._needle_radius = radius
        self._needle_width = width
        self._needle_fullscreen = fullscreen
        self._needle_pulse = pulse
        self.update()

    def set_show_stitches(self, show_stitches):
        self._show_stitches = show_stitches
        self.update()

    def set_show_grid(self, show_grid):
        self._show_grid = show_grid
        self.update()

    def initializeGL(self):
        # Re-arm cleanup so a recreated GL context can be released again.
        self._cleaned_up = False
        fmt = self.context().format()
        if is_enabled():
            logger.debug(f"[GLStitchWidget] OpenGL {fmt.majorVersion()}.{fmt.minorVersion()}")

        self._program = QOpenGLShaderProgram(self)
        self._program.addShaderFromSourceCode(QOpenGLShader.Vertex, VERTEX_SHADER)
        self._program.addShaderFromSourceCode(QOpenGLShader.Fragment, FRAGMENT_SHADER)
        if not self._program.link():
            logger.error("Shader link failed: %s", self._program.log())
            return

        self._vao = QOpenGLVertexArrayObject()
        self._vao.create()

        self._vbo = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        self._vbo.create()
        self._ibo = QOpenGLBuffer(QOpenGLBuffer.IndexBuffer)
        self._ibo.create()

        self._configure_vao()

        self._load_texture(self._texture_path or _default_texture_path())

        # Grid shader (full-screen triangle, drawn under the stitches).
        self._grid_program = QOpenGLShaderProgram(self)
        self._grid_program.addShaderFromSourceCode(QOpenGLShader.Vertex, GRID_VERTEX_SHADER)
        self._grid_program.addShaderFromSourceCode(QOpenGLShader.Fragment, GRID_FRAGMENT_SHADER)
        if not self._grid_program.link():
            logger.error("Grid shader link failed: %s", self._grid_program.log())

        # Density point shader.
        self._density_program = QOpenGLShaderProgram(self)
        self._density_program.addShaderFromSourceCode(QOpenGLShader.Vertex, DENSITY_VERTEX_SHADER)
        self._density_program.addShaderFromSourceCode(QOpenGLShader.Fragment, DENSITY_FRAGMENT_SHADER)
        if not self._density_program.link():
            logger.error("Density shader link failed: %s", self._density_program.log())

        self._density_vao = QOpenGLVertexArrayObject()
        self._density_vao.create()
        self._density_vbo = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        self._density_vbo.create()

        glEnable(GL_BLEND)
        # Premultiplied-alpha blending: the fragment shader writes colour
        # already scaled by alpha, so we add it directly and attenuate the
        # background by (1 - alpha).
        glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA)
        # Allow gl_PointSize in the density shader.
        glEnable(GL_PROGRAM_POINT_SIZE)
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
        self._width_fraction = texture_width_fraction(path)
        self._cap_fraction = texture_cap_radius_fraction(path)

        # Semicircular end-cap mask (grayscale, R channel) matching the new
        # texture. White = keep, black = trim; sampled only in the tip
        # zones. The texture holds TWO copies of the generated semicircle
        # side by side -- [as-generated | U-flipped] -- so the middle seam
        # joins the two FLAT white sides (a fully white column, sampled by
        # the ribbon body) while both arc apexes point outward:
        #   start tip: mu 0.0 (outermost) -> 0.5 (needle)  -- LEFT half,
        #   body:      mu 0.5,
        #   end tip:   mu 0.5 (needle) -> 1.0 (outermost)  -- RIGHT half.
        # A missing mask file falls back to an all-white 1x1 texture, which
        # keeps the ribbon straight-cut.
        if self._cap_texture is not None:
            self._cap_texture.destroy()
        cap_path = path.with_name(path.name.replace("_normal_mask", "_cap_mask"))
        if cap_path.exists():
            cap_src, cap_w, cap_h = _load_texture(cap_path)
            cap_data = np.concatenate([cap_src, cap_src[:, ::-1, :]], axis=1)
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
        self._cap_texture = cap_texture

    def set_texture_path(self, path):
        """Swap the thread texture at runtime (e.g. from a context menu)."""
        if self._texture is None:
            # GL context not initialised yet; remember the path for later.
            self._texture_path = path
            self._width_fraction = texture_width_fraction(path)
            self._cap_fraction = texture_cap_radius_fraction(path)
            return
        self.makeCurrent()
        self._load_texture(path)
        self.doneCurrent()
        # Width normalisation changed -> rebuild geometry.
        self._needs_upload = True
        self.update()

    def texture_path(self):
        """Return the currently active texture path (or None before init)."""
        return self._texture_path

    def _configure_vao(self):
        self._vao.bind()
        self._vbo.bind()
        self._ibo.bind()
        stride = 18 * np.dtype(np.float32).itemsize
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
        offset += 3 * np.dtype(np.float32).itemsize
        self._program.enableAttributeArray(6)
        self._program.setAttributeBuffer(6, GL_FLOAT, offset, 2, stride)
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
            width_fraction=self._width_fraction,
            cap_fraction=self._cap_fraction,
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

        w = self.width()
        h = self.height()

        # 1. Grid (GL, under everything).
        if self._show_grid:
            self._draw_grid_gl(w, h)

        # 2. Stitches (GL).
        count = min(self._visible_count, self._index_counts.shape[0])
        draw_count = int(self._index_counts[count - 1]) if count > 0 else 0
        if draw_count > 0 and self._show_stitches:
            # Vertices are in model space (see _upload_geometry). This matrix is
            # the only place zoom/pan is applied: model -> pixel (y-down) -> NDC.
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
            k_a, k_d, k_s = _lighting_coefficients(self._dark_factor, self._light_factor)
            glUniform1f(self._program.uniformLocation("u_k_a"), k_a)
            glUniform1f(self._program.uniformLocation("u_k_d"), k_d)
            glUniform1f(self._program.uniformLocation("u_k_s"), k_s)
            glUniform1f(self._program.uniformLocation("u_specular_exponent"), 12.0)
            tangent_strength, bitangent_strength = _normal_strengths(self._zoom)
            glUniform1f(self._program.uniformLocation("u_normal_strength_tangent"), tangent_strength)
            glUniform1f(self._program.uniformLocation("u_normal_strength_bitangent"), bitangent_strength)
            glUniform1i(self._program.uniformLocation("u_debug_mode"), self._debug_mode)

            self._texture.bind(0)
            glUniform1i(self._program.uniformLocation("u_texture"), 0)

            if self._cap_texture is not None:
                self._cap_texture.bind(1)
                glUniform1i(self._program.uniformLocation("u_cap_mask"), 1)

            self._vao.bind()
            glDrawElements(GL_TRIANGLES, draw_count, GL_UNSIGNED_INT, None)
            self._vao.release()
            if self._cap_texture is not None:
                self._cap_texture.release()
            self._texture.release()
            self._program.release()

        # 3. Density dots (GL points, on top of the stitches).
        if self._show_density:
            self._draw_density_gl(w, h)

        # 4. Needle crosshair (QPainter, on top of everything).
        if self._show_needle:
            self._draw_needle_gl(w, h)

        # 5. Jumps (QPainter, on top of the stitches).
        self._draw_jumps_overlay()

        # 6. Event trace overlay (QPainter, top-most).
        self._draw_trace_overlay()

        # Restore the OpenGL state that Qt's OpenGL paint engine may have
        # altered while drawing the QPainter overlays. Without this, the next
        # paintGL frame can appear washed out / blended into the background.
        glDisable(GL_DEPTH_TEST)
        glEnable(GL_BLEND)
        glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA)
        glEnable(GL_PROGRAM_POINT_SIZE)

    def _draw_trace_overlay(self):
        """Draw the viewer's event trace panel on top of the GL output."""
        viewer = self._viewer
        if (
            viewer is None
            or not getattr(viewer, "trace_events_enabled", False)
            or not getattr(viewer, "_trace_buffer", None)
        ):
            return
        margin = 8
        line_height = 16
        font = QFont("sans-serif")
        font.setStyleHint(QFont.SansSerif)
        font.setPointSize(9)
        painter = QPainter(self)
        painter.setFont(font)
        lines = [label for _, label in viewer._trace_buffer]
        max_w = max(painter.fontMetrics().horizontalAdvance(line) for line in lines)
        panel_w = max_w + margin * 2
        panel_h = len(lines) * line_height + margin * 2
        x = self.width() - panel_w - margin
        y = margin
        # Keep the panel fully opaque: writing translucent pixels to the GL
        # widget's FBO reduces the widget alpha and makes the whole embroidery
        # preview look blended/foggy when Qt composites it over the parent.
        painter.fillRect(x, y, panel_w, panel_h, QColor(32, 32, 32))
        painter.setPen(QColor(255, 255, 255))
        for i, line in enumerate(lines):
            painter.drawText(x + margin, y + margin + (i + 1) * line_height - 3, line)
        painter.end()

    def _draw_grid_gl(self, w, h):
        """Draw the measurement grid in the background using a full-screen pass."""
        if self._grid_program is None or not self._grid_program.isLinked():
            return
        self._grid_program.bind()
        glUniform2f(self._grid_program.uniformLocation("u_viewport"), float(w), float(h))
        glUniform2f(self._grid_program.uniformLocation("u_pan"), self._pan[0], self._pan[1])
        glUniform1f(self._grid_program.uniformLocation("u_zoom"), self._zoom)
        glUniform1f(self._grid_program.uniformLocation("u_zoom_ratio"), self._zoom_ratio)
        glUniform3f(self._grid_program.uniformLocation("u_bg_color"), *self._bg_color)
        glDrawArrays(GL_TRIANGLES, 0, 3)
        self._grid_program.release()

    def _draw_needle_gl(self, w, h):
        """Draw the needle crosshair on top of the stitches (QPainter).

        Matches the CPU viewer's needle: white cross with a dark outline,
        a fixed-size center ring in the needle color, and arms that extend
        with the radius (or full screen).
        """
        sx = self._needle_pos[0] * self._zoom + self._pan[0]
        sy = self._needle_pos[1] * self._zoom + self._pan[1]
        needle_x = int(sx)
        needle_y = int(sy)
        pulse = self._needle_pulse
        if self._needle_fullscreen:
            arm = max(w, h)
        else:
            arm = self._needle_radius + 66 * pulse
        radius = 6 + 18 * pulse
        outer_radius = 42 * pulse

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w = self._needle_width
        color = QColor(*self._needle_color)
        # Cross: dark outline + needle-color fill.
        painter.setPen(QPen(QColor(10, 10, 10), (8 if outer_radius else 4) * w))
        painter.drawLine(needle_x - arm, needle_y, needle_x + arm, needle_y)
        painter.drawLine(needle_x, needle_y - arm, needle_x, needle_y + arm)
        if outer_radius:
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(needle_x - outer_radius, needle_y - outer_radius,
                                outer_radius * 2, outer_radius * 2)
        painter.setPen(QPen(color, (3 if outer_radius else 2) * w))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(needle_x - radius, needle_y - radius, radius * 2, radius * 2)
        painter.drawLine(needle_x - arm, needle_y, needle_x + arm, needle_y)
        painter.drawLine(needle_x, needle_y - arm, needle_x, needle_y + arm)
        # Center dot: needle color with dark outline (fixed size).
        painter.setBrush(color)
        painter.setPen(QPen(QColor(10, 10, 10), 2 * w))
        marker_radius = 5 if outer_radius else 3
        painter.drawEllipse(needle_x - marker_radius, needle_y - marker_radius,
                            marker_radius * 2, marker_radius * 2)
        painter.end()

    def _world_to_screen(self, x, y):
        return x * self._zoom + self._pan[0], y * self._zoom + self._pan[1]

    def _draw_density_gl(self, w, h):
        """Draw density markers as GL points (one draw call, no Python loop)."""
        if self._density_program is None or not self._density_program.isLinked():
            return
        points = self._density_points
        values = self._density_values
        repeated = self._density_repeated
        visible = min(self._visible_count, points.shape[0])
        if visible == 0:
            return

        # Build interleaved vertex data: pos(2), color(3), radius(1).
        pts = points[:visible]
        vals = values[:visible]
        rep = repeated[:visible]

        colors = np.empty((visible, 3), dtype=np.float32)
        colors[:, :] = (45 / 255.0, 110 / 255.0, 215 / 255.0)  # default blue
        crit = vals >= DENSITY_CRITICAL_PER_MM2
        warn = (vals >= DENSITY_WARNING_PER_MM2) & ~crit
        colors[crit] = (220 / 255.0, 35 / 255.0, 35 / 255.0)
        colors[warn] = (235 / 255.0, 175 / 255.0, 25 / 255.0)

        radius = np.where(rep, 0.35, 0.2).astype(np.float32)
        repeated_flag = rep.astype(np.float32)

        data = np.empty((visible, 7), dtype=np.float32)
        data[:, 0:2] = pts
        data[:, 2:5] = colors
        data[:, 5] = radius
        data[:, 6] = repeated_flag

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

        self._density_program.bind()
        glUniformMatrix4fv(self._density_program.uniformLocation("u_transform"), 1, GL_FALSE, transform)
        glUniform1f(self._density_program.uniformLocation("u_zoom"), self._zoom)

        self._density_vao.bind()
        self._density_vbo.bind()
        self._density_vbo.allocate(data.tobytes(), data.nbytes)
        stride = 7 * np.dtype(np.float32).itemsize
        self._density_program.enableAttributeArray(0)
        self._density_program.setAttributeBuffer(0, GL_FLOAT, 0, 2, stride)
        self._density_program.enableAttributeArray(1)
        self._density_program.setAttributeBuffer(1, GL_FLOAT, 2 * np.dtype(np.float32).itemsize, 3, stride)
        self._density_program.enableAttributeArray(2)
        self._density_program.setAttributeBuffer(2, GL_FLOAT, 5 * np.dtype(np.float32).itemsize, 1, stride)
        self._density_program.enableAttributeArray(3)
        self._density_program.setAttributeBuffer(3, GL_FLOAT, 6 * np.dtype(np.float32).itemsize, 1, stride)
        glDrawArrays(GL_POINTS, 0, visible)
        self._density_program.disableAttributeArray(0)
        self._density_program.disableAttributeArray(1)
        self._density_program.disableAttributeArray(2)
        self._density_program.disableAttributeArray(3)
        self._density_vbo.release()
        self._density_vao.release()
        self._density_program.release()

    def _draw_jumps_overlay(self):
        """Draw jump paths on top of the stitches."""
        if not self._show_jumps:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        for x1, y1, x2, y2, risky, stitch_index in self._jump_segments:
            if stitch_index > self._visible_count:
                continue
            if self._risky_jumps_only and not risky:
                continue
            color = QColor(220, 45, 45) if risky else QColor(100, 100, 100)
            sx1, sy1 = self._world_to_screen(x1, y1)
            sx2, sy2 = self._world_to_screen(x2, y2)
            painter.setPen(QPen(color, 2, Qt.DashLine))
            painter.drawLine(int(sx1), int(sy1), int(sx2), int(sy2))
        painter.end()

    def resizeGL(self, w, h):
        glViewport(0, 0, w, h)
