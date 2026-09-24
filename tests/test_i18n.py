# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXTRACT_PATH = ROOT / "scripts" / "i18n" / "_extract.py"
LOCALES_DIR = ROOT / "src" / "inksim" / "locales"

_spec = importlib.util.spec_from_file_location("inksim_i18n_extract", EXTRACT_PATH)
assert _spec is not None and _spec.loader is not None
_extract = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_extract)

EN_CATALOG = _extract.EN_CATALOG
SRC_DIR = _extract.SRC_DIR
load_catalog = _extract.load_catalog
scan_source = _extract.scan_source


def _message_ids(catalog: dict[str, object]) -> set[str]:
    return {key for key in catalog if not key.startswith("_")}


def test_english_catalog_contains_all_extracted_strings() -> None:
    extracted = scan_source(SRC_DIR)
    catalog = load_catalog(EN_CATALOG)

    assert _message_ids(catalog) == set(extracted)
    for message_id, extracted_entry in extracted.items():
        if extracted_entry["source"] == message_id:
            continue
        catalog_entry = catalog[message_id]
        assert catalog_entry["source"] == extracted_entry["source"]
        assert catalog_entry["translation"] == extracted_entry["translation"]


def test_all_locale_catalogs_are_complete_and_translated() -> None:
    english = load_catalog(EN_CATALOG)
    english_ids = _message_ids(english)
    locale_paths = sorted(LOCALES_DIR.glob("*.json"))

    assert locale_paths
    for path in locale_paths:
        catalog = load_catalog(path)
        assert _message_ids(catalog) == english_ids, path.name
        if path.name == "en.json":
            continue

        for message_id in english_ids:
            entry = catalog[message_id]
            assert isinstance(entry, dict), f"{path.name}: invalid entry {message_id}"
            translation = entry.get("translation")
            assert isinstance(translation, str) and translation.strip(), (
                f"{path.name}: missing translation for {message_id}"
            )
            assert translation != message_id, f"{path.name}: placeholder for {message_id}"
