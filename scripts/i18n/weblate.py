#!/usr/bin/env uvr
# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Convert InkSim JSON catalogs to/from Weblate's i18next JSON format.

InkSim stores each message as ``{"source": ..., "translation": ...}`` keyed by a
stable message ID.  Weblate's i18next JSON format is a flat ``key -> value``
mapping, which is the same message-ID approach but without the source/translation
wrapper.

Export produces a ``weblate/`` directory suitable for a Weblate component:

    weblate/en.json    monolingual base language file (English source)
    weblate/cs.json    Czech translations (flat key -> value)
    ...

Import merges the flat files back into the ``{source, translation}`` catalogs.

Usage:

    uvr python scripts/i18n/weblate.py export
    uvr python scripts/i18n/weblate.py import
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
LOCALES_DIR = ROOT / "src" / "inksim" / "locales"
WEBLATE_DIR = ROOT / "weblate"


def load_catalog(path: Path) -> dict[str, Any]:
    """Return the raw catalog dict (including ``_meta``)."""
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def messages(catalog: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Return message-ID -> {source, translation} entries, dropping ``_meta``."""
    result: dict[str, dict[str, str]] = {}
    for key, value in catalog.items():
        if key.startswith("_"):
            continue
        if isinstance(value, dict):
            result[key] = {
                "source": value.get("source", key),
                "translation": value.get("translation", value.get("source", key)),
            }
        elif isinstance(value, str):
            result[key] = {"source": value, "translation": value}
    return result


def export() -> int:
    """Write flat i18next JSON files for every catalog into ``weblate/``."""
    WEBLATE_DIR.mkdir(parents=True, exist_ok=True)
    count = 0
    for path in sorted(LOCALES_DIR.glob("*.json")):
        catalog = load_catalog(path)
        meta = catalog.get("_meta", {})
        locale = meta.get("language", path.stem)
        flat: dict[str, str] = {}
        for msg_id, entry in messages(catalog).items():
            # Base (English) file uses the source text; target files use the
            # translation.  For English these are identical.
            flat[msg_id] = entry["translation"] if locale != "en" else entry["source"]
        out = WEBLATE_DIR / f"{locale}.json"
        out.write_text(json.dumps(flat, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")
        count += 1
    print(f"Exported {count} catalog(s) to {WEBLATE_DIR}.")
    return 0


def import_() -> int:
    """Merge flat i18next files back into the ``{source, translation}`` catalogs."""
    if not WEBLATE_DIR.exists():
        print(f"{WEBLATE_DIR} does not exist; run 'export' first.", file=sys.stderr)
        return 1
    count = 0
    for path in sorted(WEBLATE_DIR.glob("*.json")):
        locale = path.stem
        target = LOCALES_DIR / f"{locale}.json"
        if not target.exists():
            print(f"Skipping {path.name}: no matching catalog {target.name}.", file=sys.stderr)
            continue
        flat = load_catalog(path)
        catalog = load_catalog(target)
        meta = catalog.get("_meta", {"language": locale, "name": locale})
        for msg_id, translation in flat.items():
            if not isinstance(translation, str):
                continue
            existing = catalog.get(msg_id)
            source = existing.get("source", msg_id) if isinstance(existing, dict) else msg_id
            catalog[msg_id] = {"source": source, "translation": translation}
        ordered: dict[str, Any] = {"_meta": meta}
        ordered.update(dict(sorted(catalog.items())))
        target.write_text(
            json.dumps(ordered, ensure_ascii=False, indent=4) + "\n", encoding="utf-8"
        )
        count += 1
    print(f"Imported {count} catalog(s) from {WEBLATE_DIR}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Convert InkSim catalogs to/from i18next JSON")
    parser.add_argument("command", choices=("export", "import"), help="Direction of conversion")
    args = parser.parse_args(argv)
    return export() if args.command == "export" else import_()


if __name__ == "__main__":
    raise SystemExit(main())
