# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

from types import SimpleNamespace

import numpy as np
import pystitch as emb
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QTableWidget

from inksim.gui.frame import MainWindow
from inksim.gui.viewer import EmbroideryViewerWidget


def stitch(x, y, command):
    return (x, y, command)


def test_jump_risk_is_grouped_by_stitches_and_color_changes(qtbot, monkeypatch):
    pattern = SimpleNamespace(
        stitches=[
            stitch(0, 0, emb.JUMP),
            stitch(1, 0, emb.TRIM),
            stitch(2, 0, emb.COLOR_CHANGE),
            stitch(3, 0, emb.JUMP),
            stitch(4, 0, emb.STITCH),
            stitch(5, 0, emb.JUMP),
            stitch(6, 0, emb.TRIM),
            stitch(7, 0, emb.JUMP),
            stitch(8, 0, emb.END),
        ],
        threadlist=[],
    )
    monkeypatch.setattr("inksim.gui.viewer.emb.read", lambda path: pattern)
    viewer = EmbroideryViewerWidget(None, None)
    qtbot.addWidget(viewer)

    assert viewer.load_design("sample_design", fit_to_screen=False,
                              precompute_density=False)
    assert [segment[4] for segment in viewer.jump_segments] == [0, 0, 1, 1]
    assert "COLOR CHANGE" in viewer.command_events[0]


def test_all_supported_command_constants_are_recorded(qtbot, monkeypatch):
    pattern = SimpleNamespace(
        stitches=[
            stitch(0, 0, emb.SEQUIN_MODE),
            stitch(1, 0, emb.SEQUIN_EJECT),
            stitch(2, 0, emb.FRAME_EJECT),
            stitch(3, 0, emb.TIE_ON),
            stitch(4, 0, emb.TIE_OFF),
            stitch(5, 0, emb.STITCH),
        ],
        threadlist=[],
    )
    monkeypatch.setattr("inksim.gui.viewer.emb.read", lambda path: pattern)
    viewer = EmbroideryViewerWidget(None, None)
    qtbot.addWidget(viewer)

    assert viewer.load_design("sample_design", fit_to_screen=False,
                              precompute_density=False)
    commands = [command for events in viewer.command_events.values()
                for command in events]
    assert commands == [
        "SEQUIN_MODE", "SEQUIN_EJECT", "FRAME_EJECT", "TIE_ON", "TIE_OFF"
    ]


def test_repeated_stitches_only_compare_actual_stitch_points(qtbot, monkeypatch):
    pattern = SimpleNamespace(
        stitches=[
            stitch(0, 0, emb.STITCH),
            stitch(10, 0, emb.JUMP),
            stitch(10, 0, emb.STITCH),
            stitch(10, 0, emb.STITCH),
            stitch(10, 0, emb.END),
        ],
        threadlist=[],
    )
    monkeypatch.setattr("inksim.gui.viewer.emb.read", lambda path: pattern)
    viewer = EmbroideryViewerWidget(None, None)
    qtbot.addWidget(viewer)

    assert viewer.load_design("sample_design", fit_to_screen=False,
                              precompute_density=False)
    assert np.array_equal(
        viewer.repeated_stitch_np,
        np.array([False, False, True], dtype=np.bool_),
    )


def test_command_context_uses_current_embroidery_cursor(qtbot, monkeypatch):
    pattern = SimpleNamespace(
        stitches=[stitch(index * 10, 0, emb.STITCH) for index in range(12)],
        threadlist=[],
    )
    monkeypatch.setattr("inksim.gui.viewer.emb.read", lambda path: pattern)
    viewer = EmbroideryViewerWidget(None, None)
    qtbot.addWidget(viewer)

    assert viewer.load_design("sample_design", fit_to_screen=False,
                              precompute_density=False)
    viewer.visible_count = 7
    rows = viewer.command_context_rows()

    assert len(rows) == 11
    assert [row[2] for row in rows] == list(range(2, 13))
    assert [row[3] for row in rows].count(True) == 1
    assert rows[5][1:4] == ("STITCH", 7, True)
    assert rows[5][5:] == (6.0, 0.0)
    assert viewer.current_command_index() == 6
    viewer._set_visible_count_from_command_index(9)
    assert viewer.visible_count == 10


def test_command_dialog_table_uses_compact_columns(qtbot, monkeypatch):
    pattern = SimpleNamespace(
        stitches=[stitch(index * 10, 0, emb.STITCH) for index in range(3)],
        threadlist=[],
    )
    monkeypatch.setattr("inksim.gui.viewer.emb.read", lambda path: pattern)
    viewer = EmbroideryViewerWidget(None, None)
    qtbot.addWidget(viewer)

    assert viewer.load_design("sample_design", fit_to_screen=False,
                              precompute_density=False)
    viewer.show_command_context_dialog(QPoint(0, 0))
    qtbot.addWidget(viewer.command_dialog)
    table = viewer.command_dialog.findChild(QTableWidget)

    assert table.columnCount() == 4
    assert table.horizontalHeader().isHidden()
    assert table.item(0, 0).text() == "STITCH"
    assert table.item(0, 1).text() == "1"
    assert table.item(0, 2).text() == "0.00"
    assert table.item(0, 3).text() == "0.00"
    assert table.alternatingRowColors()
    viewer.command_dialog.close()


def test_command_dock_tracks_and_controls_embroidery_cursor(qtbot, monkeypatch):
    pattern = SimpleNamespace(
        stitches=[stitch(index * 10, 0, emb.STITCH) for index in range(5)],
        threadlist=[],
    )
    monkeypatch.setattr("inksim.gui.viewer.emb.read", lambda path: pattern)
    window = MainWindow(window_size=(640, 480))
    qtbot.addWidget(window)
    window.show()

    assert window.open_file("sample_design", precompute_density=False)
    window.show_command_panel()
    table = window.command_table

    assert window.command_dock.isVisible()
    assert table.rowCount() == 5
    assert table.item(2, 0).text() == "STITCH"
    assert table.item(2, 1).text() == "3"
    table.setCurrentCell(2, 0)
    assert window.viewer.visible_count == 3
    window.viewer.seek_to(5)
    assert table.currentRow() == 4
    assert table.item(4, 0).text() == "> STITCH"
    assert table.item(2, 0).text() == "STITCH"
    window.close()


def test_command_dock_selection_uses_command_index_after_events(qtbot, monkeypatch):
    pattern = SimpleNamespace(
        stitches=[
            stitch(0, 0, emb.STITCH),
            stitch(10, 0, emb.TRIM),
            stitch(20, 0, emb.JUMP),
            stitch(30, 0, emb.STITCH),
        ],
        threadlist=[],
    )
    monkeypatch.setattr("inksim.gui.viewer.emb.read", lambda path: pattern)
    window = MainWindow(window_size=(640, 480))
    qtbot.addWidget(window)
    window.show()

    assert window.open_file("sample_design", precompute_density=False)
    window.show_command_panel()
    table = window.command_table

    assert table.item(3, 0).text() == "> STITCH"
    table.setCurrentCell(3, 0)
    assert window.viewer.visible_count == 2
    assert table.currentRow() == 3
    window.close()
