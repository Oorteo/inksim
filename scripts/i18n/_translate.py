#!/usr/bin/env uvr
# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Incrementally translate missing or stale strings using Copilot or Ollama.

The script compares a target locale catalog (e.g. ``cs.json``) against the
English source catalog and asks a model to translate only the strings that are
missing or whose English source has changed. Translated strings are merged back
into the target catalog.

Example usage:

    uvr python scripts/i18n/_translate.py --lang cs
    uvr python scripts/i18n/_translate.py --lang sk --provider ollama

Set ``OLLAMA_HOST`` if the Ollama server is not on ``http://localhost:11434``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
LOCALES_DIR = ROOT / "src" / "inksim" / "locales"
EN_CATALOG = LOCALES_DIR / "en.json"
DEFAULT_PROVIDER = "copilot"
DEFAULT_COPILOT_MODEL = "GPT-6 Luna"
DEFAULT_OLLAMA_MODEL = "deepseek-v4-flash:cloud"


@dataclass
class TranslationJob:
    locale: str
    target_path: Path
    target_meta: dict[str, Any]
    target_messages: dict[str, dict[str, str]]
    work: dict[str, str]
    prompt: str


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
        json.dump(ordered, f, ensure_ascii=False, indent=4)
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
        if (
            target_entry.get("source") != en_source
            or not target_entry.get("translation")
            or target_entry.get("translation") == msg_id
        ):
            work[msg_id] = en_source
    return work


def build_llm_prompt(work: dict[str, str], language_name: str, locale: str) -> str:
    lines = [
        f"Translate the following UI strings for an embroidery simulator called InkSim into {language_name} ({locale})."
    ]
    lines.append("Return a single JSON object mapping each message ID to its translation.")
    lines.append("Do not wrap the JSON in Markdown fences or include text outside the JSON object.")
    lines.append("Keep technical terms consistent and use an informal tone where appropriate.")
    lines.append("")
    for msg_id, source in work.items():
        lines.append(f"{msg_id}: {source}")
    return "\n".join(lines)


def parse_copilot_response(raw: str, model: str) -> dict[str, str]:
    try:
        response = json.loads(raw)
    except json.JSONDecodeError as ex:
        raise RuntimeError(f"{model} did not return valid JSON: {ex}") from ex
    if not isinstance(response, dict):
        raise RuntimeError(f"{model} response is not a JSON object")
    return {str(key): str(value) for key, value in response.items()}


def call_copilot_batch(
    prompts: dict[str, str], model_name: str
) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    """Translate locale prompts with one client and an isolated session per locale."""
    try:
        from copilot import CopilotClient
        from copilot.session_events import AssistantMessageData
    except ImportError as ex:
        raise RuntimeError(
            "Copilot translations require the dev dependency 'github-copilot-sdk'. "
            "Install it with 'uv sync --group dev'."
        ) from ex

    async def request_translation() -> dict[str, str]:
        async with CopilotClient() as client:
            models = await client.list_models()
            model = next(
                (
                    item
                    for item in models
                    if model_name.casefold() in (item.id.casefold(), item.name.casefold())
                ),
                None,
            )
            if model is None:
                available = ", ".join(item.name for item in models)
                raise RuntimeError(
                    f"Copilot model '{model_name}' is unavailable. Available models: {available}"
                )

            translations: dict[str, dict[str, str]] = {}
            failures: dict[str, str] = {}
            for locale, prompt in prompts.items():
                try:
                    async with await client.create_session(
                        model=model.id,
                        available_tools=[],
                    ) as session:
                        response = await session.send_and_wait(prompt, timeout=300)

                    if response is None or not isinstance(response.data, AssistantMessageData):
                        raise RuntimeError(
                            f"Copilot model '{model_name}' returned no assistant message"
                        )
                    translations[locale] = parse_copilot_response(response.data.content, model_name)
                except Exception as ex:
                    failures[locale] = str(ex)
            return translations, failures

    return asyncio.run(request_translation())


def call_copilot(prompt: str, model_name: str) -> dict[str, str]:
    """Ask the signed-in Copilot account for one translation prompt."""
    translations, failures = call_copilot_batch({"": prompt}, model_name)
    if failures:
        raise RuntimeError(failures[""])
    return translations[""]


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


def translate_locales(
    locales: list[str],
    provider: str,
    model: str,
    dry_run: bool = False,
) -> int:
    """Translate missing/stale strings for each locale and update its catalog."""
    _, en_messages = load_catalog(EN_CATALOG)
    jobs: list[TranslationJob] = []
    for locale in locales:
        locale = _normalize_locale_tag(locale)
        if locale.split("-")[0] == "en":
            raise ValueError("cannot translate into the source language 'en'")

        target_path = LOCALES_DIR / f"{locale}.json"
        target_meta, target_messages = load_catalog(target_path)
        work = find_translation_work(en_messages, target_messages)
        if not work:
            print(f"No missing or stale translations for {locale}.")
            continue

        print(f"Translating {len(work)} string(s) for {locale} using {provider} ({model})...")
        language_name = target_meta.get("name", locale)
        jobs.append(
            TranslationJob(
                locale=locale,
                target_path=target_path,
                target_meta=target_meta,
                target_messages=target_messages,
                work=work,
                prompt=build_llm_prompt(work, language_name, locale),
            )
        )

    if dry_run:
        for job in jobs:
            print(f"Dry run; would send this prompt for {job.locale}:")
            print(job.prompt)
        return 0
    if not jobs:
        return 0

    translations: dict[str, dict[str, str]] = {}
    failures: dict[str, str] = {}
    if provider == "copilot":
        translations, failures = call_copilot_batch({job.locale: job.prompt for job in jobs}, model)
    else:
        for job in jobs:
            try:
                translations[job.locale] = call_ollama(job.prompt, model)
            except Exception as ex:
                failures[job.locale] = str(ex)

    total_translated = 0
    for job in jobs:
        if job.locale in failures:
            print(
                f"Translation failed for {job.locale}: {failures[job.locale]}",
                file=sys.stderr,
            )
            continue

        translated = translations[job.locale]
        for msg_id, en_source in job.work.items():
            translation = translated.get(msg_id, "")
            if not translation.strip():
                print(f"Warning: model returned empty translation for {msg_id}")
                continue
            job.target_messages[msg_id] = {
                "source": en_source,
                "translation": translation,
            }
            total_translated += 1

        job.target_meta.setdefault("language", job.locale)
        job.target_meta.setdefault("name", job.locale)
        save_catalog(job.target_path, job.target_meta, job.target_messages)
        print(f"Updated {job.target_path} with {len(translated)} translation(s).")

    return -1 if failures else total_translated


def translate_locale(
    locale: str,
    provider: str,
    model: str,
    dry_run: bool = False,
) -> int:
    """Translate missing/stale strings for one locale."""
    return translate_locales([locale], provider, model, dry_run)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Incrementally translate InkSim locale files via Copilot or Ollama"
    )
    parser.add_argument(
        "--lang",
        nargs="+",
        required=True,
        help="Target locale code(s) (e.g. cs or cs sk)",
    )
    parser.add_argument(
        "--provider",
        choices=("copilot", "ollama"),
        default=DEFAULT_PROVIDER,
        help="Translation backend (default: copilot)",
    )
    parser.add_argument(
        "--model",
        help="Model name or ID (default: GPT-6 Luna for Copilot, DeepSeek for Ollama)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print the prompt without calling the model"
    )
    args = parser.parse_args(argv)

    locales = [_normalize_locale_tag(locale) for locale in args.lang]
    if any(locale.split("-")[0] == "en" for locale in locales):
        parser.error("cannot translate into the source language 'en'")

    model = args.model or (
        DEFAULT_COPILOT_MODEL if args.provider == "copilot" else DEFAULT_OLLAMA_MODEL
    )

    try:
        return 0 if translate_locales(locales, args.provider, model, args.dry_run) >= 0 else 1
    except Exception as ex:
        print(f"Translation failed: {ex}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
