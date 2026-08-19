from types import SimpleNamespace

import numpy as np
import pystitch as emb

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
