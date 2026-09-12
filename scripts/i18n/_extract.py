#!/usr/bin/env uvr
# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Update the English source catalog from ``_("message_id")`` calls in source.

This script scans the ``src/inksim`` package for calls to the translation
helper ``_()`` and makes sure ``src/inksim/locales/en.json`` contains every
message ID with a matching English source string.  New IDs are inserted with
an empty translation field, removed IDs are deleted, and existing translations
are preserved.

Run with the project interpreter:

    uvr python scripts/i18n/_extract.py
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = ROOT / "src" / "inksim"
LOCALES_DIR = SRC_DIR / "locales"
EN_CATALOG = LOCALES_DIR / "en.json"


def _is_underscore_call(node: ast.AST) -> bool:
    """Return True when *node* is a call to ``_()``."""
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_"


def _extract_id(arg: ast.expr) -> str | None:
    """Return the string literal value when the argument is one."""
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return arg.value
    return None


def scan_source(root: Path) -> dict[str, dict[str, str]]:
    """Find all ``_("id")`` calls and map them to their fallback text.

    If the call is ``_("id", "fallback")`` the fallback is used as the source.
    Otherwise the ID itself is used as a placeholder source so a human can
    fill in the real English text later.
    """
    messages: dict[str, dict[str, str]] = {}
    for path in root.rglob("*.py"):
        if path.name.startswith("test_"):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not _is_underscore_call(node):
                continue
            if not node.args:
                continue
            msg_id = _extract_id(node.args[0])
            if msg_id is None:
                continue
            fallback = _extract_id(node.args[1]) if len(node.args) > 1 else None
            if msg_id not in messages:
                messages[msg_id] = {"source": fallback or msg_id, "translation": fallback or msg_id}
    return messages


def load_catalog(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"_meta": {"language": "en", "name": "English"}}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_catalog(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
        f.write("\n")


def update_english_catalog() -> int:
    """Refresh ``en.json`` from source.  Return number of new message IDs."""
    found = scan_source(SRC_DIR)
    catalog = load_catalog(EN_CATALOG)
    meta = catalog.pop("_meta", {"language": "en", "name": "English"})

    new_ids: list[str] = []
    for msg_id, entry in found.items():
        if msg_id not in catalog:
            new_ids.append(msg_id)
            catalog[msg_id] = entry
        else:
            # Preserve existing translation, but refresh source if a human-readable
            # fallback is introduced for an ID that previously used the ID itself.
            existing = catalog[msg_id]
            if isinstance(existing, dict):
                old_source = existing.get("source", msg_id)
                new_source = entry["source"]
                old_translation = existing.get("translation", old_source)
                if old_source == msg_id and new_source != msg_id:
                    existing["source"] = new_source
                    # For the source (English) catalog keep translation in sync
                    # with source when it was still a placeholder.
                    if old_translation == old_source:
                        existing["translation"] = new_source
                existing.setdefault("translation", entry["translation"])
            else:
                catalog[msg_id] = {
                    "source": entry["source"],
                    "translation": entry["source"],
                }

    # Remove IDs that no longer exist in source.
    for msg_id in list(catalog.keys()):
        if msg_id not in found:
            del catalog[msg_id]

    ordered: dict[str, Any] = {"_meta": meta}
    ordered.update(dict(sorted(catalog.items())))
    save_catalog(EN_CATALOG, ordered)

    if new_ids:
        print(f"Added {len(new_ids)} new message ID(s) to {EN_CATALOG}:")
        for msg_id in sorted(new_ids):
            print(f"  - {msg_id}")
    else:
        print(f"No new message IDs. {EN_CATALOG} is up to date.")
    return len(new_ids)


if __name__ == "__main__":
    sys.exit(0 if update_english_catalog() >= 0 else 1)
