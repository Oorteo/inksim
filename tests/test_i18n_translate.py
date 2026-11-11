# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TRANSLATE_PATH = ROOT / "scripts" / "i18n" / "_translate.py"

_spec = importlib.util.spec_from_file_location("inksim_i18n_translate", TRANSLATE_PATH)
assert _spec is not None and _spec.loader is not None
_translate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_translate)


def _prepare_catalogs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    locale_dir = tmp_path / "locales"
    locale_dir.mkdir()
    en_catalog = locale_dir / "en.json"
    en_catalog.write_text(
        json.dumps({"_meta": {"language": "en", "name": "English"}, "hello": {"source": "Hello"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(_translate, "LOCALES_DIR", locale_dir)
    monkeypatch.setattr(_translate, "EN_CATALOG", en_catalog)


def test_translation_cli_defaults_to_copilot_and_gpt6_luna(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _prepare_catalogs(tmp_path, monkeypatch)

    assert _translate.main(["--lang", "cs", "--dry-run"]) == 0

    assert "using copilot (GPT-6 Luna)" in capsys.readouterr().out


def test_translation_cli_uses_ollama_default_model_when_selected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _prepare_catalogs(tmp_path, monkeypatch)

    assert _translate.main(["--lang", "cs", "--provider", "ollama", "--dry-run"]) == 0

    assert "using ollama (deepseek-v4-flash:cloud)" in capsys.readouterr().out


def test_copilot_response_must_be_a_json_object() -> None:
    with pytest.raises(RuntimeError, match="did not return valid JSON"):
        _translate.parse_copilot_response("not json", "GPT-6 Luna")

    with pytest.raises(RuntimeError, match="not a JSON object"):
        _translate.parse_copilot_response("[]", "GPT-6 Luna")
