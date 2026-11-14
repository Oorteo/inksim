# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pystitch as emb
from PySide6.QtGui import QImage

from inksim.render.thumbnails import (
    THUMBNAIL_SIZE,
    build_design_preview,
    thumbnail_is_current,
    thumbnail_path,
    write_thumbnail,
)

SAMPLE = Path(__file__).parent / "data" / "sample.pes"


def _copy_sample(tmp_path: Path, name: str = "design.pes") -> Path:
    target = tmp_path / name
    target.write_bytes(SAMPLE.read_bytes())
    return target


def _thread(red: int, green: int, blue: int) -> SimpleNamespace:
    return SimpleNamespace(
        get_red=lambda: red,
        get_green=lambda: green,
        get_blue=lambda: blue,
    )


def test_thumbnail_path_keeps_the_source_name(tmp_path):
    """Each format keeps its own sidecar image: design.pes.png vs design.csv.png."""
    assert thumbnail_path(tmp_path / "design.pes") == tmp_path / "design.pes.png"
    assert thumbnail_path(tmp_path / "design.csv") == tmp_path / "design.csv.png"
    assert thumbnail_path(tmp_path / "design.pes") != thumbnail_path(tmp_path / "design.csv")


def test_write_thumbnail_creates_a_square_png(tmp_path):
    source = _copy_sample(tmp_path)

    thumbnail = write_thumbnail(source)

    assert thumbnail == source.with_name("design.pes.png")
    assert thumbnail is not None and thumbnail.is_file()
    assert thumbnail.stat().st_size > 0
    image = QImage(str(thumbnail))
    assert image.size().width() == THUMBNAIL_SIZE
    assert image.size().height() == THUMBNAIL_SIZE
    assert thumbnail_is_current(source)


def test_write_thumbnail_keeps_a_current_file(tmp_path):
    source = _copy_sample(tmp_path)
    thumbnail = write_thumbnail(source)
    assert thumbnail is not None
    first_mtime = thumbnail.stat().st_mtime_ns

    assert write_thumbnail(source) == thumbnail
    assert thumbnail.stat().st_mtime_ns == first_mtime


def test_write_thumbnail_refreshes_a_stale_file(tmp_path):
    source = _copy_sample(tmp_path)
    thumbnail = write_thumbnail(source)
    assert thumbnail is not None
    stale_mtime = os.stat(thumbnail).st_mtime_ns

    stale = source.stat().st_mtime - 10
    os.utime(thumbnail, (stale, stale))
    assert not thumbnail_is_current(source)

    assert write_thumbnail(source) == thumbnail
    assert thumbnail.stat().st_mtime_ns != stale_mtime
    assert thumbnail_is_current(source)


def test_write_thumbnail_reports_unreadable_designs(tmp_path):
    broken = tmp_path / "broken.pes"
    broken.write_bytes(b"not an embroidery file")

    assert write_thumbnail(broken) is None
    assert not (tmp_path / "broken.pes.png").exists()


def test_build_design_preview_skips_jumps_and_switches_threads():
    """Jumps move the needle without drawing; a colour change picks the next thread."""
    pattern = SimpleNamespace(
        stitches=[
            (0, 0, emb.STITCH),
            (100, 0, emb.STITCH),
            (200, 0, emb.JUMP),
            (200, 100, emb.STITCH),
            (300, 100, emb.COLOR_CHANGE),
            (400, 100, emb.STITCH),
        ],
        threadlist=[_thread(255, 0, 0), _thread(0, 0, 255)],
    )

    preview = build_design_preview(pattern)

    assert preview.stitches.shape == (4, 7)
    colors = preview.stitches[:, 4:7].astype(int).tolist()
    assert colors[0] == [255, 0, 0]
    assert colors[-1] == [0, 0, 255]
    assert preview.thread_colors == 2
    assert preview.bounds == (0.0, 0.0, 40.0, 10.0)


def test_build_design_preview_handles_an_empty_pattern():
    preview = build_design_preview(SimpleNamespace(stitches=[], threadlist=[]))

    assert preview.stitches.shape == (0, 7)
    assert preview.thread_colors == 0
