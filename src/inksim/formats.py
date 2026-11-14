# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Embroidery input-format helpers."""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pystitch as emb

from .debug import logger

_SVG_NAMESPACE = "http://www.w3.org/2000/svg"
_SVG_ROOT_TAG = f"{{{_SVG_NAMESPACE}}}svg"
_SVG_PATH_TAG = f"{{{_SVG_NAMESPACE}}}path"
_SVG_HEX_COLOR = re.compile(r"#[0-9a-fA-F]{6}\Z")

# PyStitch registers its palette files (.edr, .col, .inf) as readable formats,
# but they hold no stitches. They describe colours for designs such as DST that
# carry no palette of their own.
_COLOR_FORMAT_SUFFIX = "Color Format"
_SIDECAR_PALETTE_SUFFIXES = ("edr", "col", "inf")
_SIDECAR_SOURCE_SUFFIXES = ("hus", "pes", "jef", "vp3", "sew", "shv")

_COMMAND_NAMES: dict[int, str] = {}
for _name in dir(emb):
    if not _name.isupper() or _name.endswith("_MASK"):
        continue
    _value = getattr(emb, _name)
    if isinstance(_value, int) and 0 <= _value <= emb.COMMAND_MASK and _value not in _COMMAND_NAMES:
        _COMMAND_NAMES[_value] = _name


def command_name(command: int) -> str | None:
    """Return the PyStitch command name for *command*, or None for unknown codes."""
    return _COMMAND_NAMES.get(command)


def read_embroidery_file(path: str | Path) -> Any | None:
    """Read embroidery, including stitch-block SVGs written by PyStitch.

    Designs stored without a palette (DST and friends) borrow the colours of a
    palette file or a coloured design sitting next to them.
    """
    source = Path(path)
    if source.suffix.lower() == ".svg":
        pattern = _read_pystitch_svg(source)
        if pattern is not None:
            return pattern
    pattern = emb.read(path)
    if pattern is not None:
        palette_source = apply_sidecar_palette(pattern, source)
        if palette_source:
            logger.debug("Took the colours of %s from %s", source.name, palette_source)
    return pattern


def apply_sidecar_palette(pattern: Any, source: Path) -> str | None:
    """Colour a palette-less design from a sibling file, returning its name."""
    if getattr(pattern, "threadlist", None):
        return None
    blocks = color_block_count(pattern)
    if blocks <= 0:
        return None
    for suffix in (*_SIDECAR_PALETTE_SUFFIXES, *_SIDECAR_SOURCE_SUFFIXES):
        candidate = source.with_suffix(f".{suffix}")
        if candidate == source or not candidate.is_file():
            continue
        palette = _read_threadlist(candidate)
        if not palette:
            continue
        for thread in palette[:blocks]:
            pattern.add_thread(thread)
        return candidate.name
    return None


def _read_threadlist(path: Path) -> list[Any]:
    try:
        pattern = _read_pystitch_svg(path) if path.suffix.lower() == ".svg" else emb.read(str(path))
    except Exception:  # noqa: BLE001 - a broken palette must not break the design
        return []
    return list(getattr(pattern, "threadlist", None) or ())


def palette_sidecar_path(source: str | Path, suffix: str = "edr") -> Path:
    """Return the colour file stored next to *source* for palette-less formats."""
    return Path(source).with_suffix(f".{suffix.lstrip('.').lower()}")


def get_palette_output_formats() -> list[dict[str, str]]:
    """Return the palette formats pystitch can write, EDR first."""
    try:
        supported_formats = emb.supported_formats()
    except Exception:
        return [
            {"extension": extension, "description": extension.upper()}
            for extension in _SIDECAR_PALETTE_SUFFIXES
        ]
    found: dict[str, str] = {}
    for file_type in supported_formats:
        if file_type.get("writer") is None or not _is_color_format(file_type):
            continue
        extension = str(file_type.get("extension", "")).lstrip(".").lower()
        if extension:
            found[extension] = str(file_type.get("description", extension.upper()))
    ordered = [ext for ext in _SIDECAR_PALETTE_SUFFIXES if ext in found]
    ordered += sorted(ext for ext in found if ext not in _SIDECAR_PALETTE_SUFFIXES)
    return [{"extension": ext, "description": found[ext]} for ext in ordered]


def read_palette_file(path: str | Path) -> list[Any]:
    """Return the thread colours stored in a palette file or a coloured design."""
    return _read_threadlist(Path(path))


def write_palette_file(path: str | Path, threads: Sequence[Any]) -> None:
    """Store *threads* as an EDR palette that machines and Ink/Stitch understand."""
    palette = emb.EmbPattern()
    for thread in threads:
        palette.add_thread(thread)
    emb.write(palette, str(path))


def color_block_count(pattern: Any) -> int:
    """Return how many colour blocks the stitch data is divided into."""
    count = 1
    for stitch in getattr(pattern, "stitches", ()):
        command = stitch[2] if len(stitch) > 2 else emb.STITCH
        decoded = emb.decode_embroidery_command(command)[0]
        if decoded in (emb.COLOR_CHANGE, emb.COLOR_BREAK):
            count += 1
    return count


def is_stitchblock_svg(path: str | Path) -> bool:
    """Return whether an SVG can be read as a PyStitch stitch-block export."""
    try:
        with Path(path).open("rb") as source:
            _, root = next(ET.iterparse(source, events=("start",)))
    except (OSError, ET.ParseError, StopIteration):
        return False
    if root.tag != _SVG_ROOT_TAG or set(root.attrib) != {"version", "width", "height", "viewBox"}:
        return False
    return _read_pystitch_svg(path) is not None


def _read_pystitch_svg(path: str | Path) -> Any | None:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return None
    if root.tag != _SVG_ROOT_TAG or set(root.attrib) != {"version", "width", "height", "viewBox"}:
        return None
    if root.get("version") != "1.1":
        return None
    try:
        width = float(root.attrib["width"])
        height = float(root.attrib["height"])
        view_box = tuple(float(value) for value in root.attrib["viewBox"].split())
    except ValueError:
        return None
    if (
        len(view_box) != 4
        or not all(math.isfinite(value) for value in (width, height, *view_box))
        or width <= 0
        or height <= 0
        or view_box[2] <= 0
        or view_box[3] <= 0
        or not math.isclose(width, view_box[2])
        or not math.isclose(height, view_box[3])
    ):
        return None

    elements = list(root)
    if not elements:
        return None

    pattern = emb.EmbPattern()
    previous_color = None
    stitch_count = 0
    for element in elements:
        if (
            element.tag != _SVG_PATH_TAG
            or set(element.attrib) != {"d", "fill", "stroke", "stroke-width"}
            or element.get("fill") != "none"
            or element.get("stroke-width") != "3"
        ):
            return None
        color = element.get("stroke", "")
        if not _SVG_HEX_COLOR.fullmatch(color):
            return None
        points = _parse_pystitch_svg_points(element.get("d", ""))
        if points is None:
            return None

        if previous_color is None:
            pattern.add_thread(color)
        elif color.lower() != previous_color.lower():
            pattern.color_change()
            pattern.add_thread(color)
        pattern.move_abs(*points[0])
        for point in points[1:]:
            pattern.stitch_abs(*point)
        stitch_count += len(points) - 1
        previous_color = color

    return pattern if stitch_count > 0 else None


def _parse_pystitch_svg_points(data: str) -> list[tuple[float, float]] | None:
    tokens = data.split()
    if len(tokens) < 3 or tokens[0] != "M":
        return None
    points = []
    for token in tokens[1:]:
        coordinates = token.split(",")
        if len(coordinates) != 2:
            return None
        try:
            x, y = (float(value) for value in coordinates)
        except ValueError:
            return None
        if not math.isfinite(x) or not math.isfinite(y):
            return None
        points.append((x, y))
    return points


def get_supported_input_wildcard() -> str:
    """Build a file filter from the formats readable by pystitch."""
    extensions = get_supported_input_extensions()
    patterns = ";".join(f"*.{ext}" for ext in sorted(extensions))
    return f"Embroidery files ({patterns})|{patterns}|All files|*.*"


def get_supported_input_extensions() -> set[str]:
    """Return lowercase filename extensions readable by pystitch."""
    extensions: set[str] = set()
    try:
        supported_formats = emb.supported_formats()
    except Exception:
        return extensions
    for file_type in supported_formats:
        if file_type.get("reader") is None or _is_color_format(file_type):
            continue
        file_extensions = file_type.get("extensions", ())
        if isinstance(file_extensions, str):
            file_extensions = (file_extensions,)
        extensions.update(ext.lstrip(".").lower() for ext in file_extensions)
    return extensions


def _is_color_format(file_type: dict[str, Any]) -> bool:
    """Return whether a PyStitch format only stores thread colours."""
    return str(file_type.get("description", "")).endswith(_COLOR_FORMAT_SUFFIX)


def get_supported_output_formats() -> list[dict[str, Any]]:
    """Return writable pystitch formats with their display metadata."""
    formats: list[dict[str, Any]] = []
    try:
        supported_formats = emb.supported_formats()
    except Exception:
        return formats
    seen_extensions: set[str] = set()
    for file_type in supported_formats:
        if file_type.get("writer") is None:
            continue
        extension = file_type.get("extension", "")
        if not extension:
            continue
        extensions = file_type.get("extensions", (extension,))
        if isinstance(extensions, str):
            extensions = (extensions,)
        clean_extensions = tuple(ext.lstrip(".").lower() for ext in extensions if ext)
        if not clean_extensions:
            clean_extensions = (extension.lstrip(".").lower(),)
        primary_extension = extension.lstrip(".").lower()
        if primary_extension in seen_extensions:
            continue
        seen_extensions.add(primary_extension)
        formats.append(
            {
                "description": file_type.get("description", primary_extension.upper()),
                "extension": primary_extension,
                "extensions": clean_extensions,
            }
        )
    return sorted(formats, key=lambda item: (item["description"], item["extension"]))


def get_supported_output_filter() -> str:
    """Build a Qt file filter for all formats writable by pystitch."""
    filters: list[str] = []
    for file_type in get_supported_output_formats():
        patterns = " ".join(f"*.{ext}" for ext in file_type["extensions"])
        filters.append(f"{file_type['description']} - .{file_type['extension']} ({patterns})")
    filters.append("All files (*)")
    return ";;".join(filters)


def extension_from_output_filter(selected_filter: str) -> str:
    """Return the primary extension encoded in a Qt output-format filter."""
    suffix_marker = " - ."
    suffix_start = selected_filter.find(suffix_marker)
    if suffix_start >= 0:
        suffix_start += len(suffix_marker)
        suffix_end = selected_filter.find(" ", suffix_start)
        if suffix_end < 0:
            suffix_end = selected_filter.find("(", suffix_start)
        if suffix_end > suffix_start:
            return selected_filter[suffix_start:suffix_end].strip().lower()
    marker_start = selected_filter.find("(*.")
    if marker_start < 0:
        return ""
    marker_start += 3
    marker_end = selected_filter.find(")", marker_start)
    if marker_end < 0:
        return ""
    pattern = selected_filter[marker_start:marker_end].split()[0]
    return pattern.lstrip("*. ").lower()
