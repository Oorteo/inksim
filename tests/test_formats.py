# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import Path

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


def test_reads_sample_stitchblock_svg():
    svg_path = Path(__file__).parent / "data" / "sample_svg.svg"

    pattern = read_embroidery_file(svg_path)

    assert pattern is not None
    assert len(pattern.stitches) == 7208
    assert len(pattern.threadlist) == 2


def test_regular_svg_is_not_mistaken_for_stitchblock_export(tmp_path):
    svg_path = tmp_path / "drawing.svg"
    svg_path.write_text(
        """<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">
        <path d="M 0,0 L 10,10" fill="none" stroke="#112233" stroke-width="3"/>
        </svg>""",
        encoding="utf-8",
    )

    assert read_embroidery_file(svg_path) is None


def _write_palette_less_design(directory: Path) -> Path:
    """Write the sample as DST, which stores stitches but no palette."""
    pattern = emb.read(str(Path(__file__).parent / "data" / "sample.pes"))
    target = directory / "design.dst"
    emb.write_dst(pattern, str(target))
    return target


def _write_palette(path: Path, colors: list[str]) -> None:
    palette = emb.EmbPattern()
    for color in colors:
        palette.add_thread(color)
    emb.write(palette, str(path))


def test_color_formats_are_not_offered_as_designs():
    from inksim.formats import get_supported_input_extensions

    extensions = get_supported_input_extensions()

    assert not {"edr", "col", "inf"} & extensions
    assert {"dst", "hus", "pes"} <= extensions


def test_palette_less_design_borrows_the_sidecar_edr(tmp_path):
    design = _write_palette_less_design(tmp_path)
    _write_palette(tmp_path / "design.edr", ["#112233", "#445566", "#778899"])

    pattern = read_embroidery_file(design)

    assert [thread.hex_color() for thread in pattern.threadlist] == ["#112233", "#445566"]


def test_sidecar_edr_wins_over_a_coloured_design_next_to_it(tmp_path):
    design = _write_palette_less_design(tmp_path)
    _write_palette(tmp_path / "design.edr", ["#112233", "#445566"])
    twin = emb.read(str(Path(__file__).parent / "data" / "sample.pes"))
    emb.write_pes(twin, str(tmp_path / "design.pes"))

    pattern = read_embroidery_file(design)

    assert [thread.hex_color() for thread in pattern.threadlist] == ["#112233", "#445566"]


def test_design_without_sidecar_keeps_an_empty_palette(tmp_path):
    design = _write_palette_less_design(tmp_path)

    pattern = read_embroidery_file(design)

    assert pattern.threadlist == []


def test_palette_round_trips_through_an_edr_file(tmp_path):
    from inksim.formats import palette_sidecar_path, read_palette_file, write_palette_file

    palette_path = palette_sidecar_path(tmp_path / "design.dst")
    write_palette_file(palette_path, ["#112233", "#445566"])

    assert palette_path.name == "design.edr"
    assert [thread.hex_color() for thread in read_palette_file(palette_path)] == [
        "#112233",
        "#445566",
    ]
