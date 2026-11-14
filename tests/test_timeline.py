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
