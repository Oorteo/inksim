import numpy as np
from PySide6.QtWidgets import QApplication

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
    assert np.array_equal(high_zoom[4, 10], np.array([242, 242, 242], dtype=np.uint8))
    assert np.array_equal(solid_zoom[5, 14], np.array([235, 235, 235], dtype=np.uint8))


def test_sample_design_can_load(sample_design, qtbot):
    from inksim.gui.frame import MainWindow

    window = MainWindow(window_size=(320, 240))
    qtbot.addWidget(window)
    assert window.open_file(str(sample_design), precompute_density=False)
    assert window.viewer.stitches_np.shape[0] > 0
    window.close()
