# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Give a design the thread colours it does not store itself.

Formats such as DST keep stitches only. InkSim reads the colours of a file with
the same name next to the design, so the flow here simply lets the user point at
a palette file once and stores it as that sidecar.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QCheckBox, QFileDialog, QMessageBox, QWidget

from ..debug import logger
from ..formats import (
    get_palette_output_formats,
    get_supported_input_extensions,
    palette_sidecar_path,
    read_palette_file,
    write_palette_file,
)
from ..i18n import _


def palette_file_filter() -> str:
    """List palette files and every design format, since any may store colors."""
    palettes = " ".join(f"*.{extension}" for extension in ("edr", "col", "inf"))
    designs = " ".join(
        f"*.{extension}" for extension in sorted(get_supported_input_extensions() | {"svg"})
    )
    return ";;".join(
        (
            f"{_('dialog.palette.filter.palette', 'Palette files')} ({palettes})",
            f"{_('dialog.palette.filter.designs', 'Design files (colors when stored)')}"
            f" ({designs})",
            f"{_('dialog.palette.filter.all', 'All files')} (*)",
        )
    )


def _title() -> str:
    return _("dialog.palette.title", "Thread colors")


def choose_palette_file(parent: QWidget | None, directory: Path) -> Path | None:
    """Ask for a palette file to take the thread colors from."""
    path, _selected_filter = QFileDialog.getOpenFileName(
        parent,
        _("dialog.palette.choose", "Choose a palette or a colored design"),
        str(directory),
        palette_file_filter(),
    )
    if not path:
        return None
    return Path(path)


def palette_format(config: Any) -> str:
    """Return the palette format the user picked for stored colors."""
    value = config.get(_SAVE_PALETTE_FORMAT_KEY, "edr")
    known = {item["extension"] for item in get_palette_output_formats()}
    return value if value in known else "edr"


def _existing_palettes(source: Path) -> list[Path]:
    return [
        candidate
        for extension in ("edr", "col", "inf")
        if (candidate := palette_sidecar_path(source, extension)).is_file()
    ]


def store_palette(
    parent: QWidget | None,
    source: Path,
    threads: list[object],
    suffix: str = "edr",
) -> Path | None:
    """Write the sidecar palette for *source*, asking before replacing one."""
    target = palette_sidecar_path(source, suffix)
    existing = _existing_palettes(source)
    if existing:
        answer = QMessageBox.question(
            parent,
            _title(),
            _(
                "dialog.palette.replace",
                "{name} already stores colors for this design.\nReplace it with {target}?",
            ).format(
                name=", ".join(path.name for path in existing),
                target=target.name,
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return None
    try:
        write_palette_file(target, threads)
    except (OSError, RuntimeError, ValueError) as ex:
        logger.warning("Could not write the palette %s: %s", target, ex)
        QMessageBox.critical(
            parent,
            _title(),
            _("dialog.palette.write_failed", "Could not save the colors: {error}").format(
                error=str(ex)
            ),
        )
        return None
    for stale in existing:
        if stale != target:
            try:
                stale.unlink()
            except OSError as ex:
                logger.warning("Could not remove the old palette %s: %s", stale, ex)
    return target


def apply_palette_to_design(
    parent: QWidget | None,
    source: Path,
    blocks: int,
    config: Any,
) -> str | None:
    """Let the user pick colors for *source* and store them next to it.

    Returns a status message on success and None when nothing was stored.
    """
    chosen = choose_palette_file(parent, source.parent or Path(os.getcwd()))
    if chosen is None:
        return None
    threads = read_palette_file(chosen)
    if not threads:
        QMessageBox.warning(
            parent,
            _title(),
            _(
                "dialog.palette.empty",
                "{name} stores no thread colors.",
            ).format(name=chosen.name),
        )
        return None
    if blocks > 0 and len(threads) < blocks:
        answer = QMessageBox.question(
            parent,
            _title(),
            _(
                "dialog.palette.too_few",
                "{name} has {available} colors but the design has {blocks} color blocks."
                "\nUse it anyway? The last color will repeat.",
            ).format(name=chosen.name, available=len(threads), blocks=blocks),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return None
    selected = threads[:blocks] if blocks > 0 else threads
    target = store_palette(parent, source, list(selected), palette_format(config))
    if target is None:
        return None
    return _("status.palette_saved", "Colors of {palette} saved as {name}").format(
        palette=chosen.name, name=target.name
    )


_SAVE_PALETTE_CONFIG_KEY = "save_palette_sidecar"
_SAVE_PALETTE_FORMAT_KEY = "save_palette_format"


def store_palette_after_save(
    parent: QWidget | None,
    config: Any,
    target: Path,
    threads: list[object],
) -> Path | None:
    """Keep the thread colors of an export whose format stores none.

    The answer is remembered as ``save_palette_sidecar`` (ask/always/never) so
    saving the same format again does not ask twice.
    """
    if not threads:
        return None
    if read_palette_file(target):
        return None
    if _existing_palettes(target):
        # The design already has colors next to it, so nothing is lost.
        return None
    choice = config.get(_SAVE_PALETTE_CONFIG_KEY, "ask")
    if choice == "never":
        return None
    suffix = palette_format(config)
    if choice != "always":
        sidecar = palette_sidecar_path(target, suffix)
        box = QMessageBox(parent)
        box.setWindowTitle(_title())
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(
            _(
                "dialog.palette.save_sidecar.text",
                "{format} keeps no thread colors.\nSave them as {name} next to the design?",
            ).format(format=target.suffix.lstrip(".").upper(), name=sidecar.name)
        )
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.Yes)
        remember = QCheckBox(_("dialog.palette.save_sidecar.remember", "Remember my choice"))
        box.setCheckBox(remember)
        box.exec()
        accepted = box.standardButton(box.clickedButton()) == QMessageBox.StandardButton.Yes
        if remember.isChecked():
            try:
                config.set(_SAVE_PALETTE_CONFIG_KEY, "always" if accepted else "never")
            except OSError as ex:
                logger.warning("Could not store the palette answer: %s", ex)
        if not accepted:
            return None
    sidecar = palette_sidecar_path(target, suffix)
    try:
        write_palette_file(sidecar, threads)
    except (OSError, RuntimeError, ValueError) as ex:
        logger.warning("Could not write the palette %s: %s", sidecar, ex)
        return None
    return sidecar
