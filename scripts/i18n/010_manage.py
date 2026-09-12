#!/usr/bin/env uvr
# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Manage InkSim locale roadmap and generate missing translations.

The roadmap lives in ``locales.json`` and defines tiers:

  0  source of truth (en)
  1  core community languages (de, cs, sk)
  2  major world / European languages
  3  regional variants and large Asian languages
  4  dialects / slang / humorous variants

Examples:

    ./scripts/i18n/010_manage.py list
    ./scripts/i18n/010_manage.py add fr
    ./scripts/i18n/010_manage.py sync
    ./scripts/i18n/010_manage.py translate fr --model deepseek-v4-flash:cloud
    ./scripts/i18n/010_manage.py translate-all --tier 2 --model deepseek-v4-flash:cloud

The ``sync`` command refreshes ``src/inksim/locales/en.json`` from source and removes
orphaned keys from other locale catalogs. It does not call a translation model.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
LOCALES_DIR = ROOT / "src" / "inksim" / "locales"
ROADMAP = Path(__file__).with_suffix("").parent / "locales.json"
TRANSLATE = Path(__file__).with_suffix("").parent / "_translate.py"


def load_roadmap() -> list[dict[str, Any]]:
    with ROADMAP.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_catalog(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _count_missing(code: str, en_data: dict[str, Any]) -> int:
    if code == "en":
        return 0
    message_ids = [key for key in en_data if not key.startswith("_")]
    target_path = LOCALES_DIR / f"{code}.json"
    if not target_path.exists():
        return len(message_ids)
    target = load_catalog(target_path)
    return sum(1 for msg_id in message_ids if msg_id not in target)


def _status(code: str, exists: bool, missing: int) -> str:
    if code == "en":
        return "source"
    if not exists:
        return "missing"
    return "ready" if missing == 0 else "incomplete"


def cmd_list(argv: list[str] | None = None) -> int:
    """Print current locale coverage from the roadmap."""
    parser = argparse.ArgumentParser(description="List locale roadmap status")
    parser.add_argument("--tier", type=int, help="Only show locales up to this tier")
    args = parser.parse_args(argv or [])

    roadmap = load_roadmap()
    en_path = LOCALES_DIR / "en.json"
    en_data = load_catalog(en_path)
    en_count = sum(1 for key in en_data if not key.startswith("_"))

    print(f"{'code':<10} {'tier':<5} {'status':<12} {'missing':<8} name")
    print("-" * 60)
    for entry in roadmap:
        if args.tier is not None and entry["tier"] > args.tier:
            continue
        code = entry["code"]
        path = LOCALES_DIR / f"{code}.json"
        exists = path.exists()
        missing = _count_missing(code, en_data)
        status = _status(code, exists, missing)
        missing_str = "-" if code == "en" else str(missing)
        print(f"{code:<10} {entry['tier']:<5} {status:<12} {missing_str:<8} {entry['name']}")
    print(f"\nSource catalog 'en' has {en_count} message(s).")
    return 0


def cmd_add(argv: list[str] | None = None) -> int:
    """Create an empty catalog for a roadmap locale."""
    parser = argparse.ArgumentParser(description="Add an empty locale catalog")
    parser.add_argument("code", help="Locale code from locales.json (e.g. fr)")
    args = parser.parse_args(argv or [])

    roadmap = load_roadmap()
    entry = next((e for e in roadmap if e["code"] == args.code), None)
    if entry is None:
        print(f"Unknown locale '{args.code}'. Add it to {ROADMAP} first.", file=sys.stderr)
        return 1

    target_path = LOCALES_DIR / f"{args.code}.json"
    if target_path.exists():
        print(f"Catalog {target_path} already exists.")
        return 0

    ordered: dict[str, Any] = {"_meta": {"language": args.code, "name": entry["name"]}}
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with target_path.open("w", encoding="utf-8") as f:
        json.dump(ordered, f, ensure_ascii=False, indent=4)
        f.write("\n")
    print(f"Created empty catalog {target_path}.")
    return 0


def cmd_sync(argv: list[str] | None = None) -> int:
    """Refresh ``en.json`` from source and remove orphaned keys from locales."""
    parser = argparse.ArgumentParser(
        description="Sync locale catalogs with the English source (no auto-translation)"
    )
    _ = parser.parse_args(argv or [])

    extract = Path(__file__).with_suffix("").parent / "_extract.py"
    rc = subprocess.run([sys.executable, str(extract)], check=False).returncode
    if rc != 0:
        print("Failed to refresh English source catalog.", file=sys.stderr)
        return rc

    en_path = LOCALES_DIR / "en.json"
    en_data = load_catalog(en_path)
    canonical_keys = {key for key in en_data if not key.startswith("_")}

    removed_total = 0
    for path in sorted(LOCALES_DIR.glob("*.json")):
        if path.name == "en.json":
            continue
        data = load_catalog(path)
        meta = data.pop("_meta", {"language": path.stem, "name": path.stem})
        orphaned = [key for key in data if key not in canonical_keys]
        if not orphaned:
            continue
        for key in orphaned:
            del data[key]
        ordered: dict[str, Any] = {"_meta": meta}
        ordered.update(dict(sorted(data.items())))
        with path.open("w", encoding="utf-8") as f:
            json.dump(ordered, f, ensure_ascii=False, indent=4)
            f.write("\n")
        removed_total += len(orphaned)
        print(f"Removed {len(orphaned)} orphaned key(s) from {path.name}: {', '.join(orphaned)}")

    if removed_total == 0:
        print("No orphaned keys found; locale catalogs are in sync.")
    else:
        print(f"\nRemoved {removed_total} orphaned key(s) total.")
    return 0


def cmd_translate(argv: list[str] | None = None) -> int:
    """Translate a single locale using translate.py."""
    parser = argparse.ArgumentParser(description="Translate a single locale")
    parser.add_argument("code", help="Locale code to translate")
    parser.add_argument("--model", default="deepseek-v4-flash:cloud", help="Ollama model")
    parser.add_argument("--dry-run", action="store_true", help="Preview prompt only")
    args = parser.parse_args(argv or [])

    return subprocess.run(
        [sys.executable, str(TRANSLATE), "--lang", args.code, "--model", args.model]
        + (["--dry-run"] if args.dry_run else []),
        check=False,
    ).returncode


def cmd_translate_all(argv: list[str] | None = None) -> int:
    """Translate every roadmap locale up to a given tier."""
    parser = argparse.ArgumentParser(description="Translate all roadmap locales up to a tier")
    parser.add_argument(
        "--tier", type=int, default=2, help="Maximum tier to translate (default: 2)"
    )
    parser.add_argument("--model", default="deepseek-v4-flash:cloud", help="Ollama model")
    parser.add_argument("--dry-run", action="store_true", help="Preview prompts only")
    args = parser.parse_args(argv or [])

    roadmap = load_roadmap()
    failures = 0
    for entry in roadmap:
        code = entry["code"]
        if code == "en":
            continue
        if entry["tier"] > args.tier:
            continue
        print(f"\n=== {code} ({entry['name']}) ===")
        if not (LOCALES_DIR / f"{code}.json").exists():
            if cmd_add([code]) != 0:
                failures += 1
                continue
        rc = subprocess.run(
            [sys.executable, str(TRANSLATE), "--lang", code, "--model", args.model]
            + (["--dry-run"] if args.dry_run else []),
            check=False,
        ).returncode
        if rc != 0:
            failures += 1
    print(f"\nFinished. Failures: {failures}")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    argv = list(argv) if argv is not None else sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print("Usage: manage.py {list|add|sync|translate|translate-all} [options]")
        print("  list        --tier N")
        print("  add         <code>")
        print("  sync        Refresh en.json from source and remove orphaned keys")
        print("              from locale catalogs (does not auto-translate).")
        print("  translate   <code> [--model MODEL] [--dry-run]")
        print("  translate-all [--tier N] [--model MODEL] [--dry-run]")
        return 0 if argv and argv[0] in ("-h", "--help") else 1

    command, rest = argv[0], argv[1:]
    if command == "list":
        return cmd_list(rest)
    if command == "add":
        return cmd_add(rest)
    if command == "sync":
        return cmd_sync(rest)
    if command == "translate":
        return cmd_translate(rest)
    if command == "translate-all":
        return cmd_translate_all(rest)

    print(f"Unknown command: {command}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
