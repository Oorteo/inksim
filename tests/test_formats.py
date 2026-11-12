# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

import pystitch as emb

from inksim.formats import read_embroidery_file


def test_reads_pystitch_stitchblock_svg(tmp_path):
    svg_path = tmp_path / "stitches.svg"
    svg_path.write_text(
        """<svg version="1.1" xmlns="http://www.w3.org/2000/svg"
        width="100" height="80" viewBox="-10 -20 100 80">
        <path d="M 0,0 10,10 20,10" fill="none" stroke="#112233" stroke-width="3"/>
        <path d="M 30,30 40,40" fill="none" stroke="#aabbcc" stroke-width="3"/>
        </svg>""",
        encoding="utf-8",
    )

    pattern = read_embroidery_file(svg_path)

    assert pattern is not None
    assert pattern.threadlist[0].hex_color() == "#112233"
    assert pattern.threadlist[1].hex_color() == "#aabbcc"
    assert pattern.stitches == [
        [0.0, 0.0, emb.JUMP],
        [10.0, 10.0, emb.STITCH],
        [20.0, 10.0, emb.STITCH],
        [20.0, 10.0, emb.COLOR_CHANGE],
        [30.0, 30.0, emb.JUMP],
        [40.0, 40.0, emb.STITCH],
    ]


def test_regular_svg_is_not_mistaken_for_stitchblock_export(tmp_path):
    svg_path = tmp_path / "drawing.svg"
    svg_path.write_text(
        """<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">
        <path d="M 0,0 L 10,10" fill="none" stroke="#112233" stroke-width="3"/>
        </svg>""",
        encoding="utf-8",
    )

    assert read_embroidery_file(svg_path) is None
