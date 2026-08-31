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
