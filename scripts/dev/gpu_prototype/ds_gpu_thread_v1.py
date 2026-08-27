import sys
import numpy as np
from PySide6.QtGui import QMouseEvent, QSurfaceFormat
from PySide6.QtOpenGL import QOpenGLBuffer, QOpenGLShader, QOpenGLShaderProgram, QOpenGLVertexArrayObject
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QApplication
from OpenGL.GL import *

VERTEX_SHADER = """
#version 330 core
layout(location = 0) in vec2 a_pos;
layout(location = 1) in vec2 a_uv;
out vec2 v_uv;
void main() {
    v_uv = a_uv;
    gl_Position = vec4(a_pos, 0.0, 1.0);
}
"""

FRAGMENT_SHADER = """
#version 330 core
in vec2 v_uv;
out vec4 fragColor;

uniform vec2 u_resolution;
uniform float u_zoom;
uniform vec2 u_pan;
uniform int u_stitchCount;
uniform vec4 u_stitches[100];     // x1, y1, x2, y2
uniform vec4 u_stitchColors[100]; // r, g, b, thickness

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

    // Coarse double-helix twist: only a few turns per stitch so the two
    // strands are clearly visible, not fine noise.
    float turns = 3.0;
    float phase = along / max(len, 1e-6) * turns * 6.28318530718;
    float helixRadius = thickness * 1.35;
    vec2 helixOffset = n * helixRadius * cos(phase);
    vec2 center1 = closestOnAxis + p1 + helixOffset;
    vec2 center2 = closestOnAxis + p1 - helixOffset;

    // Render two separate strands, each with its own rounded profile.
    float strandRadius = thickness * 0.72;
    float d1 = length(world - center1) - strandRadius;
    float d2 = length(world - center2) - strandRadius;
    bool first = d1 < d2;
    float signed = min(d1, d2);

    vec2 chosen = first ? center1 : center2;
    vec2 localNormal = normalize(world - chosen);
    // Helical normal: the strand surface wraps around the stitch axis.
    float strandSign = first ? 1.0 : -1.0;
    vec2 helixTangent = normalize(t * helixRadius * cos(phase) - n * strandSign * helixRadius * sin(phase));
    vec2 helixNormal = vec2(-helixTangent.y, helixTangent.x);
    localNormal = normalize(mix(localNormal, helixNormal, 0.85));
    normal = vec3(localNormal.x, localNormal.y, sqrt(max(0.0, 1.0 - dot(localNormal, localNormal))));

    // Strand coloring: clearly separate the two intertwined threads.
    vec3 baseColor = color;
    if (first) {
        color = baseColor * 1.18;
    } else {
        color = baseColor * 0.72;
    }

    // Taper thickness toward the ends.
    float taper = 1.0 - 0.35 * abs((along / len) * 2.0 - 1.0);
    signed = signed / max(taper, 0.5);

    return signed;
}

void main() {
    vec2 uv = v_uv;
    vec2 screenPos = uv * u_resolution;
    vec2 world = (screenPos - u_pan) / u_zoom;

    vec3 bg = fabricColor(world);
    vec3 bestColor = bg;
    float bestSigned = 1e6;
    vec3 bestNormal = vec3(0.0, 0.0, 1.0);

    // Painter's order: later stitches overwrite the pixel when they cover it.
    for (int i = 0; i < u_stitchCount && i < 100; ++i) {
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
    float diffuse = 0.30 + 0.70 * ndotl;

    float tangentDotLight = dot(bestNormal.xy, lightDir.xy);
    float aniso = sqrt(max(0.0, 1.0 - tangentDotLight * tangentDotLight));
    float sheen = pow(aniso, 10.0) * 0.75;

    vec3 shaded = bestColor * diffuse;
    shaded += sheen * vec3(1.0);

    // Safe anti-alias: fade only near the edge.
    float edge = clamp(1.0 + bestSigned * 8.0, 0.0, 1.0);
    shaded = mix(bg, shaded, edge);

    fragColor = vec4(clamp(shaded, 0.0, 1.0), 1.0);
}
"""


def build_satin_stitches(rows=14, width_mm=30.0, height_mm=10.0, color=(180.0, 20.0, 40.0), thickness=0.35):
    stitches = []
    colors = []
    left = -width_mm * 0.5
    right = width_mm * 0.5
    bottom = -height_mm * 0.5
    top = height_mm * 0.5
    step_y = height_mm / rows

    for row in range(rows):
        y0 = bottom + row * step_y
        y1 = bottom + (row + 1) * step_y
        y_next = min(y1 + step_y, top)

        if row % 2 == 0:
            stitches.append([left, y0, right, y1])
            stitches.append([right, y1, left, y_next])
        else:
            stitches.append([right, y0, left, y1])
            stitches.append([left, y1, right, y_next])
        for _ in range(2):
            colors.append([*color, thickness])

    return np.array(stitches, dtype=np.float32), np.array(colors, dtype=np.float32)


class ThreadGLWidget(QOpenGLWidget):
    def __init__(self, stitches, colors, parent=None):
        super().__init__(parent)
        self.stitches = stitches
        self.colors = colors

        all_points = []
        for s in stitches:
            all_points.append([s[0], s[1]])
            all_points.append([s[2], s[3]])
        all_points = np.array(all_points)
        center = all_points.mean(axis=0)

        print(f"Střed stehů: {center}")
        print(f"Počet stehů: {len(stitches)}")

        self._program = None
        self._vao = None
        self._vbo = None

        self.zoom = 12.0
        self.pan = np.array([self.width() / 2.0, self.height() / 2.0], dtype=np.float32) - center * self.zoom

        self._dragging = False
        self._last_mouse = None
        self.setMouseTracking(True)

    def initializeGL(self):
        print("=== INITIALIZEGL ===")

        self._program = QOpenGLShaderProgram(self)
        self._program.addShaderFromSourceCode(QOpenGLShader.Vertex, VERTEX_SHADER)
        self._program.addShaderFromSourceCode(QOpenGLShader.Fragment, FRAGMENT_SHADER)
        self._program.link()

        if not self._program.isLinked():
            print("CHYBA:", self._program.log())
            return

        print("Shader program linked successfully")
        self._program.bind()

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

        stride = 16
        self._program.enableAttributeArray(0)
        self._program.setAttributeBuffer(0, 0x1406, 0, 2, stride)
        self._program.enableAttributeArray(1)
        self._program.setAttributeBuffer(1, 0x1406, 8, 2, stride)

        self._vbo.release()
        self._vao.release()

        print("=== INITIALIZEGL HOTOVO ===")

    def paintGL(self):
        gl = self.context().functions()

        gl.glClearColor(0.92, 0.90, 0.86, 1.0)
        gl.glClear(0x00004000)

        if not self._program or not self._program.isLinked():
            return

        self._program.bind()
        self._vao.bind()

        loc_res = self._program.uniformLocation("u_resolution")
        loc_zoom = self._program.uniformLocation("u_zoom")
        loc_pan = self._program.uniformLocation("u_pan")
        loc_count = self._program.uniformLocation("u_stitchCount")

        glUniform2f(loc_res, float(self.width()), float(self.height()))
        glUniform1f(loc_zoom, float(self.zoom))
        glUniform2f(loc_pan, float(self.pan[0]), float(self.pan[1]))

        count = min(self.stitches.shape[0], 100)
        glUniform1i(loc_count, count)

        for i in range(count):
            s = self.stitches[i]
            c = self.colors[i]
            loc_s = self._program.uniformLocation(f"u_stitches[{i}]")
            loc_c = self._program.uniformLocation(f"u_stitchColors[{i}]")
            if loc_s >= 0:
                glUniform4f(loc_s, float(s[0]), float(s[1]), float(s[2]), float(s[3]))
            if loc_c >= 0:
                glUniform4f(loc_c, float(c[0]), float(c[1]), float(c[2]), float(c[3]))

        gl.glDrawArrays(0x0005, 0, 4)

        self._vao.release()
        self._program.release()

    def resizeGL(self, w, h):
        pass

    def mousePressEvent(self, event: QMouseEvent):
        pos = np.array([event.position().x(), event.position().y()])
        pos[1] = self.height() - pos[1]
        self._last_mouse = pos
        self._dragging = True

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._dragging = False

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._dragging and self._last_mouse is not None:
            pos = np.array([event.position().x(), event.position().y()])
            pos[1] = self.height() - pos[1]
            delta = pos - self._last_mouse
            self.pan[0] += delta[0]
            self.pan[1] += delta[1]
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

    stitches, colors = build_satin_stitches(rows=14)
    print(f"Vytvořeno {len(stitches)} stehů")

    widget = ThreadGLWidget(stitches, colors)
    widget.setWindowTitle("InkSim GPU Thread Prototype v1")
    widget.resize(800, 600)
    widget.show()

    print("\n=== HOTOVO ===")
    print("GPU prototyp s double-helix twist, osvětlením a sheen.")

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
