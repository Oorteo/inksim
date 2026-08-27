import sys
from pathlib import Path

import numpy as np
from PySide6.QtCore import QSize
from PySide6.QtGui import QImage, QMouseEvent, QSurfaceFormat, QVector2D, QVector4D
from PySide6.QtOpenGL import QOpenGLBuffer, QOpenGLShader, QOpenGLShaderProgram, QOpenGLVertexArrayObject
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QApplication, QMainWindow

HERE = Path(__file__).resolve().parent

VERTEX_SHADER = """#version 330 core
layout(location = 0) in vec2 a_pos;
layout(location = 1) in vec2 a_uv;
out vec2 v_uv;
void main() {
    v_uv = a_uv;
    gl_Position = vec4(a_pos, 0.0, 1.0);
}
"""

FRAGMENT_SHADER_DEBUG = """#version 330 core
in vec2 v_uv;
out vec4 fragColor;
uniform int u_stitchCount;
uniform float u_zoom;
void main() {
    vec2 uv = v_uv;
    if (u_stitchCount > 0) {
        fragColor = vec4(0.0, 1.0, 0.0, 1.0); // green if uniforms arrive
    } else {
        fragColor = vec4(uv.x, uv.y, u_zoom / 20.0, 1.0);
    }
}
"""

FRAGMENT_SHADER = """#version 330 core
in vec2 v_uv;
out vec4 fragColor;

uniform vec2 u_resolution;
uniform float u_zoom;
uniform vec2 u_pan;
uniform float u_lightFactor;
uniform float u_darkFactor;
uniform int u_stitchCount;
uniform vec4 u_stitches[100];    // x1,y1,x2,y2
uniform vec4 u_stitchColors[100]; // r,g,b,thickness

vec3 fabricColor(vec2 world) {
    float grain = fract(sin(dot(world * 0.1, vec2(12.9898, 78.233))) * 43758.5453);
    float weave = sin(world.x * 8.0) * sin(world.y * 8.0) * 0.03;
    vec3 base = vec3(0.92, 0.90, 0.86);
    return base * (0.96 + 0.04 * grain) + vec3(weave);
}

float stitchSdf(int i, vec2 world, out vec3 normal, out vec3 color) {
    vec4 a = u_stitches[i];
    vec4 b = u_stitchColors[i];
    vec2 p1 = a.xy;
    vec2 p2 = a.zw;
    color = b.rgb / 255.0;
    float thickness = b.a;

    vec2 axis = p2 - p1;
    float len = length(axis);
    if (len < 1e-6) {
        return 1e6;
    }
    vec2 t = axis / len;
    vec2 n = vec2(-t.y, t.x);

    vec2 toPoint = world - p1;
    float along = dot(toPoint, t);
    vec2 closestOnAxis = clamp(along, 0.0, len) * t;

    // Capsule SDF with double-helix twist applied only at the closest axis point.
    float twistFreq = 15.0;
    float phase = along * twistFreq;
    float helixRadius = thickness * 0.35;
    vec2 helixOffset = n * helixRadius * cos(phase);
    vec2 center1 = closestOnAxis + p1 + helixOffset;
    vec2 center2 = closestOnAxis + p1 - helixOffset;

    float d1 = length(world - center1);
    float d2 = length(world - center2);
    bool first = d1 < d2;
    float signed = min(d1, d2) - thickness;

    vec2 chosen = first ? center1 : center2;
    vec2 localNormal = normalize(world - chosen);
    localNormal += n * 0.25 * sin(phase);
    localNormal = normalize(localNormal);
    normal = vec3(localNormal.x, localNormal.y, sqrt(max(0.0, 1.0 - dot(localNormal, localNormal))));

    // Taper thickness toward the ends.
    float taper = 1.0 - 0.35 * abs((along / len) * 2.0 - 1.0);
    signed = signed / max(taper, 0.5);

    return signed;
}

void main() {
    vec2 uv = v_uv * u_resolution;
    vec2 world = (uv - u_pan) / u_zoom;

    vec3 bg = fabricColor(world);
    vec3 bestColor = bg;
    float bestSigned = 1e6;
    vec3 bestNormal = vec3(0.0, 0.0, 1.0);

    // Painter's order: later stitches overwrite the pixel when they cover it.
    for (int i = 0; i < u_stitchCount; ++i) {
        vec3 n;
        vec3 col;
        float d = stitchSdf(i, world, n, col);
        if (d < 0.0) {
            bestSigned = d;
            bestNormal = n;
            bestColor = col;
        }
    }

    if (bestSigned > 0.0) {
        fragColor = vec4(bg, 1.0);
        return;
    }

    vec3 lightDir = normalize(vec3(-0.4, -0.4, 0.82));
    float ndotl = max(dot(bestNormal, lightDir), 0.0);
    float diffuse = 0.35 + 0.65 * ndotl;

    float tangentDotLight = dot(bestNormal.xy, lightDir.xy);
    float aniso = sqrt(max(0.0, 1.0 - tangentDotLight * tangentDotLight));
    float sheen = pow(aniso, 12.0) * u_lightFactor;

    float darkScale = 1.0 - 0.45 * u_darkFactor;
    vec3 shaded = bestColor * darkScale * diffuse;
    shaded += sheen * vec3(1.0);

    // Safe anti-alias: fade only near the edge, no extrapolation beyond [0,1].
    float edge = clamp(1.0 + bestSigned * 8.0, 0.0, 1.0);
    shaded = mix(bg, shaded, edge);

    fragColor = vec4(clamp(shaded, 0.0, 1.0), 1.0);
}
"""


def build_satin_stitches(rows=14, width_mm=30.0, height_mm=10.0, color=(180.0, 20.0, 40.0)):
    stitches = []
    left = -width_mm * 0.5
    right = width_mm * 0.5
    bottom = -height_mm * 0.5
    top = height_mm * 0.5
    step_y = height_mm / rows
    thickness = 0.35
    for row in range(rows):
        y0 = bottom + row * step_y
        y1 = bottom + (row + 1) * step_y
        if row % 2 == 0:
            stitches.append((left, y0, right, y1, *color, thickness))
            # Connecting stitch only until the last valid row boundary.
            y_next = min(y1 + step_y, top)
            stitches.append((right, y1, left, y_next, *color, thickness))
        else:
            stitches.append((right, y0, left, y1, *color, thickness))
            y_next = min(y1 + step_y, top)
            stitches.append((left, y1, right, y_next, *color, thickness))
    return np.array(stitches, dtype=np.float32)


class ThreadGLWidget(QOpenGLWidget):
    def __init__(self, stitches, parent=None):
        super().__init__(parent)
        self.stitches = stitches
        self._program = None
        self._vao = None
        self._vbo = None
        self.zoom = 12.0
        self.pan = np.array([400.0, 300.0], dtype=np.float32)
        self.setMouseTracking(True)
        self._dragging = False
        self._last_mouse = None

    def initializeGL(self):
        self._program = QOpenGLShaderProgram(self)
        ok_vs = self._program.addShaderFromSourceCode(QOpenGLShader.Vertex, VERTEX_SHADER)
        ok_fs = self._program.addShaderFromSourceCode(QOpenGLShader.Fragment, FRAGMENT_SHADER)
        print(f"vertex shader compiled: {ok_vs}")
        print(f"fragment shader compiled: {ok_fs}")
        print(f"shader compile log: {self._program.log()}")
        ok_link = self._program.link()
        print(f"program linked: {ok_link}")
        print(f"program link log: {self._program.log()}")
        self._program.bind()


        # Two triangles as a triangle strip: 4 vertices.
        vertices = np.array([
            -1.0, -1.0, 0.0, 0.0,
             1.0, -1.0, 1.0, 0.0,
            -1.0,  1.0, 0.0, 1.0,
             1.0,  1.0, 1.0, 1.0,
        ], dtype=np.float32)

        self._vao = QOpenGLVertexArrayObject(self)
        self._vao.create()
        self._vao.bind()

        self._vbo = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        self._vbo.create()
        self._vbo.bind()
        self._vbo.allocate(vertices.tobytes(), vertices.nbytes)

        self._program.enableAttributeArray(0)
        self._program.setAttributeBuffer(0, 0x1406, 0, 2, 16)  # GL_FLOAT
        self._program.enableAttributeArray(1)
        self._program.setAttributeBuffer(1, 0x1406, 8, 2, 16)

        self._vbo.release()
        self._vao.release()

    def paintGL(self):
        gl = self.context().functions()
        gl.glClearColor(0.92, 0.90, 0.86, 1.0)
        gl.glClear(0x00004000 | 0x00000100)  # GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT

        self._program.bind()
        self._vao.bind()
        self._program.setUniformValue(self._program.uniformLocation("u_resolution"), QVector2D(float(self.width()), float(self.height())))
        self._program.setUniformValue(self._program.uniformLocation("u_zoom"), float(self.zoom))
        self._program.setUniformValue(self._program.uniformLocation("u_pan"), QVector2D(float(self.pan[0]), float(self.pan[1])))
        self._program.setUniformValue(self._program.uniformLocation("u_lightFactor"), 0.55)
        self._program.setUniformValue(self._program.uniformLocation("u_darkFactor"), 0.45)

        count = min(self.stitches.shape[0], 100)
        self._program.setUniformValue(self._program.uniformLocation("u_stitchCount"), count)

        for i in range(count):
            s = self.stitches[i]
            self._program.setUniformValue(
                self._program.uniformLocation(f"u_stitches[{i}]"),
                QVector4D(float(s[0]), float(s[1]), float(s[2]), float(s[3]))
            )
            self._program.setUniformValue(
                self._program.uniformLocation(f"u_stitchColors[{i}]"),
                QVector4D(float(s[4]), float(s[5]), float(s[6]), float(s[7]))
            )

        gl = self.context().functions()
        gl.glDrawArrays(0x0005, 0, 4)  # GL_TRIANGLE_STRIP
        self._vao.release()

    def resizeGL(self, w, h):
        pass

    def mousePressEvent(self, event: QMouseEvent):
        self._dragging = True
        self._last_mouse = np.array([event.position().x(), event.position().y()])

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._dragging = False

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._dragging and self._last_mouse is not None:
            pos = np.array([event.position().x(), event.position().y()])
            delta = pos - self._last_mouse
            self.pan += delta
            self._last_mouse = pos
            self.update()

    def wheelEvent(self, event):
        delta = event.angleDelta().y() / 120.0
        self.zoom *= 1.1 ** delta
        self.update()


def main():
    app = QApplication(sys.argv)

    fmt = QSurfaceFormat()
    fmt.setRenderableType(QSurfaceFormat.OpenGL)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setVersion(3, 3)
    QSurfaceFormat.setDefaultFormat(fmt)

    stitches = build_satin_stitches(rows=14)
    widget = ThreadGLWidget(stitches)
    widget.setWindowTitle("InkSim GL Thread Prototype")
    widget.resize(800, 600)
    widget.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
