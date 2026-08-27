import importlib
import math
import sys
from pathlib import Path

import numpy as np
from PySide6.QtCore import QUrl
from PySide6.QtGui import QImage, QVector3D, QVector4D
from PySide6.QtQuick import QQuickView
from PySide6.QtWidgets import QApplication

HERE = Path(__file__).resolve().parent


def build_satin_stitches(
    rows: int = 12,
    cols: int = 40,
    width_mm: float = 30.0,
    height_mm: float = 10.0,
    color: tuple[float, float, float] = (180.0, 20.0, 40.0),
):
    """Return a synthetic satin zigzag as [x1, y1, x2, y2, r, g, b, thickness]."""
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
            stitches.append((right, y1, left, y1 + step_y, *color, thickness))
        else:
            stitches.append((right, y0, left, y1, *color, thickness))
            stitches.append((left, y1, right, y1 + step_y, *color, thickness))
    return np.array(stitches, dtype=np.float32)


def create_stitch_texture(stitches: np.ndarray) -> QImage:
    """Pack stitch rows into a float32 RGBA image for the shader.

    Layout per stitch (4 horizontal pixels):
        pixel 0: (x1, y1, x2, y2)
        pixel 1: (r,  g,  b,  thickness)
    All other rows are unused but kept for alignment.
    """
    count = stitches.shape[0]
    data = np.zeros((count, 4, 4), dtype=np.float32)
    for i, (x1, y1, x2, y2, r, g, b, thickness) in enumerate(stitches):
        data[i, 0] = (x1, y1, 0.0, 0.0)
        data[i, 1] = (x2, y2, 0.0, 0.0)
        data[i, 2] = (r, g, b, 0.0)
        data[i, 3] = (thickness, 0.0, 0.0, 0.0)
    # Flatten to interleaved RGBA and create QImage Format_RGBX32FPx4 / similar.
    flat = data.reshape(count * 4, 4)
    # Use RGBA32F: each pixel = 4 floats. Qt Format is RGBA32F = 31? Not
    # exposed in PySide6 enums reliably; use QImage.Format.Format_RGBX64? No.
    # Easiest portable way: upload via QImage.Format_RGBA8888 loses precision.
    # Instead encode floats into bytes directly and use Format_RGBA32FPx4
    # which equals QImage.Format.Format_RGBA32FPx4 (value 34 in Qt6).
    raw = flat.astype(np.float32).tobytes()
    image = QImage(raw, 4, count, QImage.Format.Format_RGBA32FPx4)
    return image.copy()  # detach from temporary raw buffer


def main():
    app = QApplication(sys.argv)

    stitches = build_satin_stitches(rows=14, cols=60)
    stitch_image = create_stitch_texture(stitches)

    view = QQuickView()
    view.setResizeMode(QQuickView.SizeRootObjectToView)

    # Expose uniforms.
    view.rootContext().setContextProperty(
        "stitchTexture", stitch_image
    )
    view.rootContext().setContextProperty(
        "uStitchCount", float(stitches.shape[0])
    )
    view.rootContext().setContextProperty(
        "uZoom", 12.0
    )
    view.rootContext().setContextProperty(
        "uPan", QVector3D(400.0, 300.0, 0.0)
    )
    view.rootContext().setContextProperty(
        "uThreadRadius", 0.35
    )
    view.rootContext().setContextProperty(
        "uLightFactor", 0.55
    )
    view.rootContext().setContextProperty(
        "uDarkFactor", 0.45
    )

    qml_path = HERE / "thread_scene.qml"
    view.setSource(QUrl.fromLocalFile(str(qml_path)))
    if view.status() != QQuickView.Ready:
        print("QML load errors:", view.errors(), file=sys.stderr)
        sys.exit(1)

    view.resize(800, 600)
    view.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
