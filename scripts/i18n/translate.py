#!/usr/bin/env uvr
# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Incrementally translate missing or stale strings using a local LLM.

The script compares a target locale catalog (e.g. ``cs.json``) against the
English source catalog and asks an Ollama model to translate only the strings
that are missing or whose English source has changed.  Translated strings are
merged back into the target catalog.

Example usage:

    uvr python scripts/i18n/translate.py --lang cs --model deepseek-v4-flash:cloud
    uvr python scripts/i18n/translate.py --lang sk --model deepseek-v4-flash:cloud

Set ``OLLAMA_HOST`` if the Ollama server is not on ``http://localhost:11434``.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
LOCALES_DIR = ROOT / "src" / "inksim" / "locales"
EN_CATALOG = LOCALES_DIR / "en.json"
DEFAULT_MODEL = "deepseek-v4-flash:cloud"


def load_catalog(path: Path) -> tuple[dict[str, Any], dict[str, dict[str, str]]]:
    """Return (meta, messages) for a catalog file."""
    if not path.exists():
        return {"language": path.stem, "name": path.stem}, {}
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    meta = data.pop("_meta", {"language": path.stem, "name": path.stem})
    messages: dict[str, dict[str, str]] = {}
    for key, value in data.items():
        if isinstance(value, dict):
            messages[key] = value
        elif isinstance(value, str):
            messages[key] = {"source": value, "translation": value}
    return meta, messages


def save_catalog(path: Path, meta: dict[str, Any], messages: dict[str, dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered: dict[str, Any] = {"_meta": meta}
    ordered.update(dict(sorted(messages.items())))
    with path.open("w", encoding="utf-8") as f:
        json.dump(ordered, f, ensure_ascii=False, indent=2)
        f.write("\n")


def find_translation_work(
    en_messages: dict[str, dict[str, str]],
    target_messages: dict[str, dict[str, str]],
) -> dict[str, str]:
    """Return message IDs that need translation, mapped to current English source."""
    work: dict[str, str] = {}
    for msg_id, en_entry in en_messages.items():
        en_source = en_entry.get("source", msg_id)
        target_entry = target_messages.get(msg_id)
        if target_entry is None:
            work[msg_id] = en_source
            continue
        if target_entry.get("source") != en_source:
            work[msg_id] = en_source
    return work


def build_llm_prompt(work: dict[str, str], language_name: str, locale: str) -> str:
    lines = [
        f"Translate the following UI strings for an embroidery simulator called InkSim into {language_name} ({locale})."
    ]
    lines.append("Return a single JSON object mapping each message ID to its translation.")
    lines.append("Keep technical terms consistent and use an informal tone where appropriate.")
    lines.append("")
    for msg_id, source in work.items():
        lines.append(f"{msg_id}: {source}")
    return "\n".join(lines)


def call_ollama(prompt: str, model: str) -> dict[str, str]:
    """Ask Ollama for a JSON response and parse the translations."""
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
    }
    try:
        import urllib.request

        req = urllib.request.Request(
            f"{host}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            response = json.loads(resp.read().decode("utf-8"))
    except Exception as ex:
        # Fallback to CLI when the HTTP API is unavailable.
        result = subprocess.run(
            ["ollama", "run", model, prompt],
            capture_output=True,
            text=True,
            check=False,
        )
        response_text = result.stdout or result.stderr
        try:
            response = json.loads(response_text)
        except json.JSONDecodeError as decode_err:
            raise RuntimeError(f"Could not parse Ollama response: {decode_err}") from ex

    raw = response.get("response", response.get("content", response))
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as decode_err:
            raise RuntimeError(f"Model did not return valid JSON: {decode_err}") from None
    if not isinstance(raw, dict):
        raise RuntimeError("Model response is not a JSON object")
    return {k: str(v) for k, v in raw.items()}


def _normalize_locale_tag(value: str) -> str:
    """Normalize ``pt_BR.UTF-8`` to ``pt-BR``."""
    value = value.strip()
    value = value.split(".")[0]
    value = value.replace("_", "-")
    parts = value.split("-")
    if parts:
        parts[0] = parts[0].lower()
        parts[1:] = [part.upper() for part in parts[1:]]
    return "-".join(parts)


def translate_locale(locale: str, model: str, dry_run: bool = False) -> int:
    """Translate missing/stale strings for *locale* and update its catalog."""
    locale = _normalize_locale_tag(locale)
    en_meta, en_messages = load_catalog(EN_CATALOG)
    target_path = LOCALES_DIR / f"{locale}.json"
    target_meta, target_messages = load_catalog(target_path)

    work = find_translation_work(en_messages, target_messages)
    if not work:
        print(f"No missing or stale translations for {locale}.")
        return 0

    print(f"Translating {len(work)} string(s) for {locale} using {model}...")
    language_name = target_meta.get("name", locale)
    prompt = build_llm_prompt(work, language_name, locale)

    if dry_run:
        print("Dry run; would send this prompt:")
        print(prompt)
        return 0

    translated = call_ollama(prompt, model)

    for msg_id, en_source in work.items():
        translation = translated.get(msg_id, "")
        if not translation.strip():
            print(f"Warning: model returned empty translation for {msg_id}")
            continue
        target_messages[msg_id] = {
            "source": en_source,
            "translation": translation,
        }

    target_meta.setdefault("language", locale)
    target_meta.setdefault("name", language_name)
    save_catalog(target_path, target_meta, target_messages)
    print(f"Updated {target_path} with {len(translated)} translation(s).")
    return len(translated)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Incrementally translate InkSim locale files via Ollama"
    )
    parser.add_argument("--lang", required=True, help="Target locale code (e.g. cs, sk)")
    parser.add_argument(
        "--model", default=DEFAULT_MODEL, help=f"Ollama model to use (default: {DEFAULT_MODEL})"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print the prompt without calling the model"
    )
    args = parser.parse_args(argv)

    locale = _normalize_locale_tag(args.lang)
    if locale.split("-")[0] == "en":
        parser.error("cannot translate into the source language 'en'")

    try:
        return 0 if translate_locale(locale, args.model, args.dry_run) >= 0 else 1
    except Exception as ex:
        print(f"Translation failed: {ex}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
