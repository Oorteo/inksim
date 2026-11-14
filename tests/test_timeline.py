# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

import numpy as np
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QWheelEvent

from inksim.gui.timeline import TimelineWidget


class TimelineViewer:
    def __init__(self, total=100):
        self.stitches_np = np.zeros((total, 7), dtype=np.float32)
        self.visible_count = 0
        self.command_events = {}
        self.play_step = 1
        self.play_speed = 1
        self.bounds = (0, 0, 0, 0)
        self.color_count = 0

    def highlight_needle(self):
        pass


def make_timeline(qtbot, total=100):
    viewer = TimelineViewer(total)
    timeline = TimelineWidget(None, viewer)
    qtbot.addWidget(timeline)
    timeline.resize(400, 64)
    return timeline, viewer


def test_ctrl_wheel_zooms_around_pointer(qtbot):
    timeline, _ = make_timeline(qtbot)
    pointer_x = 158
    wheel_event = QWheelEvent(
        QPoint(pointer_x, 14),
        QPoint(pointer_x, 14),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.NoButton,
        Qt.ControlModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )

    timeline.wheelEvent(wheel_event)

    assert (timeline._view_start, timeline._view_end) == (5, 85)
    assert timeline._view_start + 0.25 * (timeline._view_end - timeline._view_start) == 25


def test_unmodified_wheel_adjusts_waveform_scale_only_over_main_timeline(qtbot):
    timeline, _ = make_timeline(qtbot)
    main_bar, overview, _ = timeline._layout_rects()
    wheel_event = QWheelEvent(
        main_bar.center(),
        main_bar.center(),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.NoButton,
        Qt.NoModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )

    timeline.wheelEvent(wheel_event)

    assert timeline.waveform_scale_mm == 4

    overview_event = QWheelEvent(
        overview.center(),
        overview.center(),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.NoButton,
        Qt.NoModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )
    timeline.wheelEvent(overview_event)

    assert timeline.waveform_scale_mm == 4


def test_seek_maps_pointer_to_zoomed_range(qtbot):
    timeline, _ = make_timeline(qtbot)
    timeline._view_start = 20
    timeline._view_end = 40
    seeks = []
    timeline.seek_requested.connect(seeks.append)

    timeline.seek(392)

    assert seeks == [40]


def test_overview_moves_zoomed_range_without_changing_its_scale(qtbot):
    timeline, _ = make_timeline(qtbot)
    timeline._view_start = 20
    timeline._view_end = 40
    _, overview, _ = timeline._layout_rects()
    viewport = timeline._overview_viewport(overview, 100)
    timeline._overview_drag_offset = viewport.width() / 2

    timeline._pan_overview_to(overview.left() + overview.width() / 2)

    assert (timeline._view_start, timeline._view_end) == (40, 60)


def test_new_design_resets_timeline_to_full_range(qtbot):
    timeline, viewer = make_timeline(qtbot)
    timeline._view_start = 20
    timeline._view_end = 40
    viewer.stitches_np = np.zeros((50, 7), dtype=np.float32)

    assert timeline._sync_view() == 50
    assert (timeline._view_start, timeline._view_end) == (0, 50)


def test_stitch_waveform_scale_details_short_lengths_and_compresses_long_ones():
    amplitude = TimelineWidget._stitch_waveform_amplitude

    assert amplitude(0, 10, 5) == 1
    assert amplitude(2.5, 10, 5) == 5
    assert amplitude(5, 10, 5) == 10
    assert amplitude(100_000, 10, 5) == 10
    assert amplitude(5, 10, 10) == 5


def test_timeline_renders_zoomed_view_with_command_markers(qtbot):
    timeline, viewer = make_timeline(qtbot)
    timeline._view_start = 20
    timeline._view_end = 40
    viewer.stitches_np[:, 4:7] = [30, 100, 180]
    viewer.command_events = {25: ["TRIM", "JUMP"], 30: ["COLOR CHANGE"]}

    image = timeline.grab()
    _, overview, _ = timeline._layout_rects()
    viewport = timeline._overview_viewport(overview, 100)
    viewport_frame = viewport.adjusted(0, -4, 0, 4)

    assert not image.isNull()
    assert viewport_frame.top() < overview.top()
    assert viewport_frame.bottom() > overview.bottom()
    outside_pixel = image.toImage().pixelColor(overview.left() + 20, overview.center().y())
    selected_pixel = image.toImage().pixelColor(viewport.center().x(), overview.center().y())
    assert outside_pixel.lightness() > selected_pixel.lightness()


def test_zoomed_timeline_draws_stitch_lengths_symmetrically(qtbot):
    timeline, viewer = make_timeline(qtbot, total=2)
    viewer.stitches_np = np.array(
        [
            [0, 0, 6, 0, 220, 30, 30],
            [0, 0, 12, 0, 30, 70, 220],
        ],
        dtype=np.float32,
    )
    viewer.visible_count = 2
    timeline.waveform_scale_mm = 12
    timeline._view_start = 0
    timeline._view_end = 2

    image = timeline.grab().toImage()
    main_bar, _, _ = timeline._layout_rects()
    center_y = main_bar.center().y()
    first_x = main_bar.left() + int(0.5 / 2 * main_bar.width())
    second_x = main_bar.left() + int(1.5 / 2 * main_bar.width())
    first_color_above = image.pixelColor(first_x, center_y - 4)
    first_color_below = image.pixelColor(first_x, center_y + 4)
    second_color_above = image.pixelColor(second_x, center_y - 9)
    second_color_below = image.pixelColor(second_x, center_y + 9)

    assert first_color_above.red() > first_color_above.blue()
    assert first_color_below.red() > first_color_below.blue()
    assert second_color_above.blue() > second_color_above.red()
    assert second_color_below.blue() > second_color_below.red()


def test_zoomed_out_waveform_does_not_fill_stitch_rectangles(qtbot):
    timeline, viewer = make_timeline(qtbot, total=1000)
    viewer.stitches_np = np.tile(
        np.array([[0, 0, 1, 0, 220, 30, 30]], dtype=np.float32),
        (1000, 1),
    )
    viewer.visible_count = len(viewer.stitches_np)

    image = timeline.grab().toImage()
    main_bar, _, _ = timeline._layout_rects()
    pixel = image.pixelColor(main_bar.center().x(), main_bar.top() + 1)

    assert pixel.blue() > 150


def test_stitches_above_waveform_scale_have_clipped_end_marks(qtbot):
    timeline, viewer = make_timeline(qtbot, total=1)
    viewer.stitches_np = np.array([[0, 0, 20, 0, 220, 30, 30]], dtype=np.float32)
    viewer.visible_count = 1

    image = timeline.grab().toImage()
    main_bar, _, _ = timeline._layout_rects()
    stitch_x = main_bar.center().x()
    cap_y = main_bar.center().y() - (main_bar.height() - 4) // 2
    cap_pixel = image.pixelColor(stitch_x + 1, cap_y)

    assert cap_pixel.red() > cap_pixel.green() * 2
    assert cap_pixel.red() > cap_pixel.blue() * 2
