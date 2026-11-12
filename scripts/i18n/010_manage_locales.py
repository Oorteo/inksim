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

    ./scripts/i18n/010_manage_locales.py list
    ./scripts/i18n/010_manage_locales.py add fr
    ./scripts/i18n/010_manage_locales.py sync
    ./scripts/i18n/010_manage_locales.py translate fr
    ./scripts/i18n/010_manage_locales.py translate-all --tier 2
    ./scripts/i18n/010_manage_locales.py translate fr --provider ollama

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


def _translation_command(
    codes: list[str],
    provider: str,
    model: str | None,
    dry_run: bool,
) -> list[str]:
    command = [
        sys.executable,
        str(TRANSLATE),
        "--lang",
        *codes,
        "--provider",
        provider,
    ]
    if model:
        command.extend(["--model", model])
    if dry_run:
        command.append("--dry-run")
    return command


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


def _count_needs_update(code: str, en_data: dict[str, Any]) -> int:
    if code == "en":
        return 0
    message_ids = [key for key in en_data if not key.startswith("_")]
    target = load_catalog(LOCALES_DIR / f"{code}.json")

    def needs_update(msg_id: str) -> bool:
        target_entry = target[msg_id]
        if isinstance(target_entry, dict):
            target_source = target_entry.get("source")
            translation = target_entry.get("translation")
        elif isinstance(target_entry, str):
            target_source = translation = target_entry
        else:
            return True

        english_entry = en_data[msg_id]
        english_source = (
            english_entry.get("source", msg_id)
            if isinstance(english_entry, dict)
            else english_entry
        )
        return not translation or translation == msg_id or target_source != english_source

    return sum(1 for msg_id in message_ids if msg_id in target and needs_update(msg_id))


def _status(code: str, exists: bool, missing: int, needs_update: int) -> str:
    if code == "en":
        return "source"
    if not exists:
        return "missing"
    return "ready" if missing == 0 and needs_update == 0 else "incomplete"


def cmd_list(argv: list[str] | None = None) -> int:
    """Print current locale coverage from the roadmap."""
    parser = argparse.ArgumentParser(description="List locale roadmap status")
    parser.add_argument("--tier", type=int, help="Only show locales up to this tier")
    args = parser.parse_args(argv or [])

    roadmap = load_roadmap()
    en_path = LOCALES_DIR / "en.json"
    en_data = load_catalog(en_path)
    en_count = sum(1 for key in en_data if not key.startswith("_"))

    print(f"{'code':<10} {'tier':<5} {'status':<12} {'missing':<8} {'needs update':<14} name")
    print("-" * 78)
    for entry in roadmap:
        if args.tier is not None and entry["tier"] > args.tier:
            continue
        code = entry["code"]
        path = LOCALES_DIR / f"{code}.json"
        exists = path.exists()
        missing = _count_missing(code, en_data)
        needs_update = _count_needs_update(code, en_data)
        status = _status(code, exists, missing, needs_update)
        missing_str = "-" if code == "en" else str(missing)
        needs_update_str = "-" if code == "en" else str(needs_update)
        print(
            f"{code:<10} {entry['tier']:<5} {status:<12} {missing_str:<8} "
            f"{needs_update_str:<14} {entry['name']}"
        )
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
    """Translate a single locale using the selected provider."""
    parser = argparse.ArgumentParser(description="Translate a single locale")
    parser.add_argument("code", help="Locale code to translate")
    parser.add_argument(
        "--provider",
        choices=("copilot", "ollama"),
        default="copilot",
        help="Translation backend (default: copilot)",
    )
    parser.add_argument("--model", help="Model name or ID (defaults based on provider)")
    parser.add_argument("--dry-run", action="store_true", help="Preview prompt only")
    args = parser.parse_args(argv or [])

    return subprocess.run(
        _translation_command([args.code], args.provider, args.model, args.dry_run),
        check=False,
    ).returncode


def cmd_translate_all(argv: list[str] | None = None) -> int:
    """Translate every roadmap locale up to a given tier."""
    parser = argparse.ArgumentParser(description="Translate all roadmap locales up to a tier")
    parser.add_argument(
        "--tier", type=int, default=2, help="Maximum tier to translate (default: 2)"
    )
    parser.add_argument(
        "--provider",
        choices=("copilot", "ollama"),
        default="copilot",
        help="Translation backend (default: copilot)",
    )
    parser.add_argument("--model", help="Model name or ID (defaults based on provider)")
    parser.add_argument("--dry-run", action="store_true", help="Preview prompts only")
    args = parser.parse_args(argv or [])

    roadmap = load_roadmap()
    failures = 0
    codes = []
    for entry in roadmap:
        code = entry["code"]
        if code == "en":
            continue
        if entry["tier"] > args.tier:
            continue
        print(f"\n=== {code} ({entry['name']}) ===", flush=True)
        if not (LOCALES_DIR / f"{code}.json").exists():
            if cmd_add([code]) != 0:
                failures += 1
                continue
        codes.append(code)

    if codes:
        rc = subprocess.run(
            _translation_command(codes, args.provider, args.model, args.dry_run),
            check=False,
        ).returncode
        if rc != 0:
            failures += 1
    print(f"\nFinished. Failures: {failures}")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    argv = list(argv) if argv is not None else sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print("Usage: 010_manage_locales.py {list|add|sync|translate|translate-all} [options]")
        print("  list        --tier N")
        print("  add         <code>")
        print("  sync        Refresh en.json from source and remove orphaned keys")
        print("              from locale catalogs (does not auto-translate).")
        print("  translate   <code> [--provider copilot|ollama] [--model MODEL] [--dry-run]")
        print("  translate-all [--tier N] [--provider copilot|ollama] [--model MODEL] [--dry-run]")
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
