# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Documentation links must point at existing files and headings."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKIPPED_DIRECTORIES = {".git", ".venv", "__pycache__", "dist", "htmlcov", "node_modules"}
DOCUMENTS = sorted(
    path
    for path in ROOT.rglob("*.md")
    if not SKIPPED_DIRECTORIES.intersection(path.relative_to(ROOT).parts)
)
MARKDOWN_LINK = re.compile(r"\]\((?P<target>[^)\s]+)")
HTML_LINK = re.compile(r"(?:src|href)=(?P<quote>[\"'])(?P<target>.+?)(?P=quote)")
HEADING = re.compile(r"^#{1,6}\s+(?P<text>.+)$", re.MULTILINE)


def _slug(text: str) -> str:
    """Return the GitHub anchor of a heading."""
    plain = text.strip().lower()
    plain = re.sub(r"[^\w\s-]", "", plain)
    return plain.replace(" ", "-")


def _without_fenced_code(text: str) -> str:
    """Remove complete Markdown fenced blocks, respecting their marker and length."""
    visible_lines = []
    fence_character = None
    fence_length = 0
    for line in text.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        indentation = len(content) - len(content.lstrip(" "))
        marker_start = indentation
        if indentation <= 3 and marker_start < len(content):
            marker = content[marker_start]
            if marker in {"`", "~"}:
                marker_end = marker_start
                while marker_end < len(content) and content[marker_end] == marker:
                    marker_end += 1
                run_length = marker_end - marker_start
                remainder = content[marker_end:]
                if fence_character is None:
                    if run_length >= 3 and not (marker == "`" and "`" in remainder):
                        fence_character = marker
                        fence_length = run_length
                    if fence_character is not None:
                        continue
                elif marker == fence_character:
                    if run_length >= fence_length and not remainder.strip(" \t"):
                        fence_character = None
                        fence_length = 0
                    continue
        if fence_character is None:
            visible_lines.append(line)
    return "".join(visible_lines)


def _headings(path: Path) -> set[str]:
    text = _without_fenced_code(path.read_text(encoding="utf-8"))
    return {_slug(match.group("text")) for match in HEADING.finditer(text)}


def _link_targets(path: Path) -> list[str]:
    text = _without_fenced_code(path.read_text(encoding="utf-8"))
    targets = [match.group("target") for match in MARKDOWN_LINK.finditer(text)]
    targets.extend(match.group("target") for match in HTML_LINK.finditer(text))
    return [unquote(target) for target in targets]


def _is_external(target: str) -> bool:
    return "://" in target or target.startswith("mailto:")


def _resolved_path(document: Path, path_part: str) -> Path:
    """Resolve a documentation path; a leading slash means the repository root."""
    if path_part.startswith("/"):
        return ROOT / path_part.lstrip("/")
    return document.parent / path_part


def test_document_anchors_ignore_headings_in_fenced_code(tmp_path: Path):
    document = tmp_path / "guide.md"
    document.write_text("# Real heading\n\n```\n# Example heading\n```\n", encoding="utf-8")

    assert _slug("real heading") in _headings(document)
    assert _slug("example heading") not in _headings(document)


def test_document_anchors_respect_fence_character_length_and_closing_lines(tmp_path: Path):
    document = tmp_path / "guide.md"
    document.write_text(
        "# Visible heading\n\n"
        "````python\n"
        "```\n"
        "# Hidden backtick heading\n"
        "``` trailing text\n"
        "````\n\n"
        "~~~text\n"
        "# Hidden tilde heading\n"
        "~~~~\n\n"
        "# Another visible heading\n",
        encoding="utf-8",
    )

    headings = _headings(document)

    assert _slug("visible heading") in headings
    assert _slug("another visible heading") in headings
    assert _slug("hidden backtick heading") not in headings
    assert _slug("hidden tilde heading") not in headings


@pytest.mark.parametrize("document", DOCUMENTS, ids=lambda path: str(path.relative_to(ROOT)))
def test_document_links_resolve(document: Path):
    broken = []
    for target in _link_targets(document):
        if _is_external(target):
            continue
        path_part = target.split("#", 1)[0]
        if path_part and not _resolved_path(document, path_part).exists():
            broken.append(target)

    assert not broken, f"{document.relative_to(ROOT)} links to missing targets: {broken}"


@pytest.mark.parametrize("document", DOCUMENTS, ids=lambda path: str(path.relative_to(ROOT)))
def test_document_anchors_resolve(document: Path):
    broken = []
    for target in _link_targets(document):
        if _is_external(target) or "#" not in target:
            continue
        path_part, _, anchor = target.partition("#")
        target_document = _resolved_path(document, path_part) if path_part else document
        if not target_document.is_file() or not anchor:
            continue
        if anchor not in _headings(target_document):
            broken.append(target)

    assert not broken, f"{document.relative_to(ROOT)} links to missing anchors: {broken}"
