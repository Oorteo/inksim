from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QWidget

from inksim.gui.shortcuts import ViewerShortcutFilter


def key_event(key, modifiers=Qt.NoModifier):
    return QKeyEvent(QKeyEvent.KeyPress, key, modifiers)


def test_arrow_alt_and_wasd_shortcuts(qtbot):
    window = QWidget()
    qtbot.addWidget(window)
    viewer = type(
        "ShortcutViewer",
        (),
        {
            "stitches_np": __import__("numpy").zeros((100, 7)),
            "visible_count": 10,
            "step_size": 10,
            "_last_dir": 1,
            "is_playing": False,
            "pan_x": 100,
            "pan_y": 100,
            "zoom": 1.0,
            "shading_step": 0.05,
            "progress_bar": None,
            "invalidate_cache": lambda self: None,
            "update": lambda self: None,
            "update_mode_indicators": lambda self: None,
        },
    )()
    viewer.window = lambda: window
    viewer.center_design = lambda: None
    viewer.fit_to_screen = lambda: None
    viewer.set_one_to_one = lambda: None
    viewer.toggle_display_mode = lambda mode: None
    viewer.show_help = lambda: None
    viewer.show_settings = lambda: None
    viewer.select_renderer = lambda: None
    viewer.toggle_auto_play = lambda: None
    viewer.fullscreen_requested = type("Signal", (), {"emit": lambda self: None})()
    viewer.show_needle = False
    viewer.highlight_needle = lambda: None
    viewer.stop_needle_highlight = lambda: None

    shortcut_filter = ViewerShortcutFilter(window, viewer)
    assert shortcut_filter.handle_key_event(key_event(Qt.Key_Right))
    assert viewer.visible_count == 20
    assert shortcut_filter.handle_key_event(
        key_event(Qt.Key_Left, Qt.AltModifier))
    assert viewer.visible_count == 19

    original_pan = (viewer.pan_x, viewer.pan_y)
    assert shortcut_filter.handle_key_event(key_event(Qt.Key_W))
    assert shortcut_filter.handle_key_event(key_event(Qt.Key_A))
    assert shortcut_filter.handle_key_event(key_event(Qt.Key_S))
    assert shortcut_filter.handle_key_event(key_event(Qt.Key_D))
    assert (viewer.pan_x, viewer.pan_y) == original_pan


def test_alt_wheel_steps_with_angle_and_pixel_delta(qtbot):
    from inksim.gui.viewer import EmbroideryViewerWidget

    viewer = EmbroideryViewerWidget(None, None)
    qtbot.addWidget(viewer)
    viewer.stitches_np = __import__("numpy").zeros((10, 7))
    viewer.visible_count = 4

    angle_event = QWheelEvent(
        QPoint(10, 10), QPoint(10, 10), QPoint(0, 0), QPoint(0, 120),
        Qt.NoButton, Qt.AltModifier, Qt.ScrollPhase.ScrollUpdate, False,
    )
    viewer.wheelEvent(angle_event)
    assert viewer.visible_count == 5

    pixel_event = QWheelEvent(
        QPoint(10, 10), QPoint(10, 10), QPoint(0, 15), QPoint(0, 0),
        Qt.NoButton, Qt.AltModifier, Qt.ScrollPhase.ScrollUpdate, False,
    )
    viewer.wheelEvent(pixel_event)
    assert viewer.visible_count == 6

    ctrl_event = QWheelEvent(
        QPoint(10, 10), QPoint(10, 10), QPoint(0, 0), QPoint(0, -120),
        Qt.NoButton, Qt.ControlModifier, Qt.ScrollPhase.ScrollUpdate, False,
    )
    viewer.wheelEvent(ctrl_event)
    assert viewer.visible_count == 5


def test_double_click_seek_selects_nearest_visible_stitch(qtbot):
    import numpy as np
    from inksim.gui.viewer import EmbroideryViewerWidget

    viewer = EmbroideryViewerWidget(None, None)
    qtbot.addWidget(viewer)
    viewer.stitches_np = np.array(
        [
            [10, 10, 30, 10, 255, 0, 0],
            [30, 10, 50, 10, 0, 255, 0],
            [50, 10, 70, 10, 0, 0, 255],
        ],
        dtype=np.float32,
    )
    viewer.visible_count = 3
    viewer.zoom = 1.0
    viewer.pan_x = 100
    viewer.pan_y = 50

    assert viewer.seek_to_screen_stitch(QPoint(142, 60))
    assert viewer.visible_count == 2
    assert not viewer.seek_to_screen_stitch(QPoint(10, 10))
    assert viewer.visible_count == 2


def test_minimum_zoom_keeps_small_design_visible(qtbot):
    from inksim.gui.viewer import EmbroideryViewerWidget

    viewer = EmbroideryViewerWidget(None, None)
    qtbot.addWidget(viewer)
    viewer.bounds = (0, 0, 2, 1)

    assert viewer.minimum_zoom() == 50.0


def test_maximum_zoom_is_based_on_ten_millimeter_viewport_span(qtbot):
    from inksim.gui.viewer import EmbroideryViewerWidget

    viewer = EmbroideryViewerWidget(None, None)
    qtbot.addWidget(viewer)
    viewer.resize(1200, 800)

    assert viewer.maximum_zoom() == 120.0
