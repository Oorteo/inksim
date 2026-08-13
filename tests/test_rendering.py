import numpy as np
from PySide6.QtWidgets import QApplication

from inksim.render.export import render_export_image
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


def test_sample_design_can_load(sample_design, qtbot):
    from inksim.gui.frame import MainWindow

    window = MainWindow(window_size=(320, 240))
    qtbot.addWidget(window)
    assert window.open_file(str(sample_design), precompute_density=False)
    assert window.viewer.stitches_np.shape[0] > 0
    window.close()
