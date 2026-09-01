# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import Path

import numpy as np
from PySide6.QtWidgets import QApplication

from inksim.formats import (
    extension_from_output_filter,
    get_supported_output_filter,
    get_supported_output_formats,
)
from inksim.render.export import render_export_image
from inksim.render.grid import render_grid_numba
from inksim.render.registry import STITCH_RENDERERS
from inksim.gui.viewer import EmbroideryViewerWidget


def test_all_registered_renderers_export_without_crashing(qapp, tmp_path):
    stitches = np.array(
        [
            [0, 0, 10, 10, 220, 30, 40],
            [10, 10, 20, 0, 30, 100, 220],
        ],
        dtype=np.float32,
    )
    bounds = (0, 0, 20, 10)

    for renderer in STITCH_RENDERERS:
        image = render_export_image(
            stitches,
            bounds,
            96,
            64,
            0.4,
            renderer.key,
            dpi=96,
        )
        output = tmp_path / f"{renderer.key}.png"
        assert image.save(str(output), "PNG")
        assert output.stat().st_size > 0


def test_grid_adds_one_millimeter_lines_only_at_high_zoom():
    low_zoom = np.full((32, 32, 3), 255, dtype=np.uint8)
    high_zoom = np.full((32, 32, 3), 255, dtype=np.uint8)
    solid_zoom = np.full((32, 32, 3), 255, dtype=np.uint8)

    render_grid_numba(low_zoom, 4.0, 0.0, 0.0)
    render_grid_numba(high_zoom, 10.0, 0.0, 0.0)
    render_grid_numba(solid_zoom, 14.0, 0.0, 0.0)

    assert np.array_equal(low_zoom[4, 4], np.array([255, 255, 255], dtype=np.uint8))
    # Fine grid is now blended with the background at ~15% strength.
    assert np.array_equal(high_zoom[4, 10], np.array([216, 216, 216], dtype=np.uint8))
    assert np.array_equal(solid_zoom[5, 14], np.array([216, 216, 216], dtype=np.uint8))


def test_supported_output_filter_lists_writable_pystitch_formats():
    formats = get_supported_output_formats()
    extensions = {file_type["extension"] for file_type in formats}
    output_filter = get_supported_output_filter()

    assert "dst" in extensions
    assert "pes" in extensions
    assert "Tajima Embroidery Format - .dst (*.dst)" in output_filter
    assert "Brother Embroidery Format - .pes (*.pes)" in output_filter
    assert extension_from_output_filter("Brother Embroidery Format - .pes (*.pes)") == "pes"
    assert extension_from_output_filter("Tajima Embroidery Format (*.dst) (*.dst)") == "dst"
    assert extension_from_output_filter("Scalable Vector Graphics (*.svg *.svgz)") == "svg"


def test_sample_design_can_load(sample_design, qtbot):
    from inksim.gui.frame import MainWindow

    window = MainWindow(window_size=(320, 240))
    qtbot.addWidget(window)
    assert window.open_file(str(sample_design), precompute_density=False)
    assert window.viewer.stitches_np.shape[0] > 0
    window.close()


def test_switching_from_gpu_hides_widget_without_destroying_gl_resources():
    class FakeGLWidget:
        def __init__(self):
            self.hidden = False
            self.cleanup_calls = 0

        def hide(self):
            self.hidden = True

        def cleanup(self):
            self.cleanup_calls += 1

    gl_widget = FakeGLWidget()
    viewer = type(
        "ViewerState",
        (),
        {"active_renderer": "cpu_raster", "_gl_widget": gl_widget},
    )()

    EmbroideryViewerWidget._update_gl_widget_visibility(viewer)

    assert gl_widget.hidden
    assert gl_widget.cleanup_calls == 0


def test_save_as_embroidery_writes_pystitch_format(sample_design, qtbot, tmp_path):
    from inksim.gui.frame import MainWindow

    window = MainWindow(window_size=(320, 240))
    qtbot.addWidget(window)
    assert window.open_file(str(sample_design), precompute_density=False)

    output_path = tmp_path / "saved.dst"
    assert window.save_embroidery_to_path(output_path)
    assert output_path.is_file()
    assert output_path.stat().st_size > 0
    window.close()


def test_save_as_extension_helper_replaces_current_suffix(qtbot):
    from inksim.gui.frame import MainWindow

    window = MainWindow(window_size=(320, 240))
    qtbot.addWidget(window)

    assert window._path_with_output_extension("design.dst", "pes") == "design.pes"
    assert window._path_with_output_extension("design", "pes") == "design.pes"
    window.close()


def test_document_path_controls_save_as_default(qtbot, tmp_path):
    from inksim.gui.frame import MainWindow

    document_path = tmp_path / "KL.svg"
    document_path.write_text("<svg/>", encoding="utf-8")
    window = MainWindow(window_size=(320, 240), document_path=document_path)
    qtbot.addWidget(window)
    window.current_file_path = Path("/tmp/transient.csv")

    assert window._default_save_name() == "KL.csv"
    assert window._default_save_path() == tmp_path.resolve() / "KL.csv"
    assert window._default_export_name(".png") == "KL.png"
    assert window.document_path == document_path.resolve()
    assert window.last_directory == str(tmp_path.resolve())
    window.close()
