# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
TRANSLATE_PATH = ROOT / "scripts" / "i18n" / "_translate.py"

_spec = importlib.util.spec_from_file_location("inksim_i18n_translate", TRANSLATE_PATH)
assert _spec is not None and _spec.loader is not None
_translate = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _translate
_spec.loader.exec_module(_translate)

MANAGE_PATH = ROOT / "scripts" / "i18n" / "010_manage_locales.py"
_manage_spec = importlib.util.spec_from_file_location("inksim_i18n_manage", MANAGE_PATH)
assert _manage_spec is not None and _manage_spec.loader is not None
_manage = importlib.util.module_from_spec(_manage_spec)
_manage_spec.loader.exec_module(_manage)


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


def test_copilot_response_rejects_non_string_translations() -> None:
    with pytest.raises(RuntimeError, match="non-string translation for 'hello'"):
        _translate.parse_copilot_response('{"hello": null}', "GPT-6 Luna")


def test_translation_preparation_failure_does_not_skip_other_locales(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _prepare_catalogs(tmp_path, monkeypatch)
    locale_dir = _translate.LOCALES_DIR
    (locale_dir / "cs.json").write_text("{invalid json", encoding="utf-8")
    monkeypatch.setattr(
        _translate,
        "call_ollama",
        lambda _prompt, _model: {"hello": "Ahoj"},
    )

    result = _translate.translate_locales(["cs", "sk"], "ollama", "test-model")

    assert result == -1
    assert json.loads((locale_dir / "sk.json").read_text(encoding="utf-8"))["hello"] == {
        "source": "Hello",
        "translation": "Ahoj",
    }
    assert "Preparing translation for cs failed" in capsys.readouterr().err


def test_catalog_write_failure_does_not_skip_other_locales(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _prepare_catalogs(tmp_path, monkeypatch)
    save_catalog = _translate.save_catalog

    def fail_czech_catalog(path, meta, messages):
        if path.name == "cs.json":
            raise OSError("permission denied")
        save_catalog(path, meta, messages)

    monkeypatch.setattr(_translate, "save_catalog", fail_czech_catalog)
    monkeypatch.setattr(
        _translate,
        "call_ollama",
        lambda _prompt, _model: {"hello": "Ahoj"},
    )

    result = _translate.translate_locales(["cs", "sk"], "ollama", "test-model")

    assert result == -1
    assert not (_translate.LOCALES_DIR / "cs.json").exists()
    assert json.loads((_translate.LOCALES_DIR / "sk.json").read_text(encoding="utf-8"))[
        "hello"
    ] == {
        "source": "Hello",
        "translation": "Ahoj",
    }
    assert "Ollama translation for cs failed" in capsys.readouterr().err


def test_ollama_non_string_translation_is_reported_for_affected_locale(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _prepare_catalogs(tmp_path, monkeypatch)

    class FakeResponse:
        def __init__(self, value: str) -> None:
            self.value = value

        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps({"response": self.value}).encode("utf-8")

    def fake_urlopen(request: object, timeout: int) -> FakeResponse:
        payload = json.loads(request.data)
        translations = {"hello": None if "(cs)" in payload["prompt"] else "Ahoj"}
        return FakeResponse(json.dumps(translations))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = _translate.translate_locales(["cs", "sk"], "ollama", "test-model")

    assert result == -1
    assert not (tmp_path / "locales" / "cs.json").exists()
    assert (
        json.loads((tmp_path / "locales" / "sk.json").read_text(encoding="utf-8"))["hello"][
            "translation"
        ]
        == "Ahoj"
    )
    error = capsys.readouterr().err
    assert "Ollama translation for cs failed" in error
    assert "non-string translation for 'hello' (NoneType)" in error


def test_translation_cli_accepts_multiple_locales(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _prepare_catalogs(tmp_path, monkeypatch)

    assert _translate.main(["--lang", "cs", "sk", "--dry-run"]) == 0

    output = capsys.readouterr().out
    assert "for cs:" in output
    assert "for sk:" in output


def test_copilot_batch_reuses_client_with_one_session_per_locale(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    clients = []
    completed_locales = []
    monkeypatch.setattr(_translate, "COPILOT_PROGRESS_INTERVAL_SECONDS", 0.005)

    class AssistantMessageData:
        def __init__(self, content: str) -> None:
            self.content = content

    class FakeSession:
        def __init__(self) -> None:
            self.prompts = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def send_and_wait(self, prompt: str, timeout: int):
            self.prompts.append((prompt, timeout))
            await asyncio.sleep(0.02)
            return SimpleNamespace(data=AssistantMessageData(json.dumps({"hello": "translated"})))

    class FakeClient:
        def __init__(self) -> None:
            self.sessions = []
            self.model_list_calls = 0
            clients.append(self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def list_models(self):
            self.model_list_calls += 1
            return [SimpleNamespace(id="model-id", name="GPT-6 Luna")]

        async def create_session(self, **_kwargs):
            session = FakeSession()
            self.sessions.append(session)
            return session

    copilot_module = ModuleType("copilot")
    copilot_module.__path__ = []
    copilot_module.CopilotClient = FakeClient
    events_module = ModuleType("copilot.session_events")
    events_module.AssistantMessageData = AssistantMessageData
    monkeypatch.setitem(sys.modules, "copilot", copilot_module)
    monkeypatch.setitem(sys.modules, "copilot.session_events", events_module)

    translations, failures = _translate.call_copilot_batch(
        {"cs": "Translate into Czech", "sk": "Translate into Slovak"},
        "GPT-6 Luna",
        on_translation=lambda locale, _translation: completed_locales.append(locale),
    )

    assert failures == {}
    assert translations == {
        "cs": {"hello": "translated"},
        "sk": {"hello": "translated"},
    }
    assert len(clients) == 1
    assert clients[0].model_list_calls == 1
    assert len(clients[0].sessions) == 2
    assert clients[0].sessions[0].prompts == [("Translate into Czech", 300)]
    assert clients[0].sessions[1].prompts == [("Translate into Slovak", 300)]
    assert completed_locales == ["cs", "sk"]
    output = capsys.readouterr().out
    assert "Waiting for Copilot response for cs" in output
    assert "Completed cs in" in output
    assert "Estimated remaining:" in output


def test_locale_list_counts_stale_and_untranslated_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    locale_dir = tmp_path / "locales"
    locale_dir.mkdir()
    (locale_dir / "cs.json").write_text(
        json.dumps(
            {
                "stale": {"source": "Old source", "translation": "Překlad"},
                "empty": {"source": "Empty", "translation": ""},
                "placeholder": {
                    "source": "Placeholder",
                    "translation": "placeholder",
                },
                "ready": {"source": "Ready", "translation": "Připraveno"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(_manage, "LOCALES_DIR", locale_dir)

    en_messages = {
        "stale": {"source": "Current source"},
        "empty": {"source": "Empty"},
        "placeholder": {"source": "Placeholder"},
        "ready": {"source": "Ready"},
        "missing": {"source": "Missing"},
    }
    target_messages = json.loads((locale_dir / "cs.json").read_text(encoding="utf-8"))

    assert _manage._count_missing("cs", en_messages) == 1
    assert _manage._count_needs_update("cs", en_messages) == 3
    assert len(_translate.find_translation_work(en_messages, target_messages)) == 4
