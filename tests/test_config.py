# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the TOML-backed Config module."""

import json
import threading
from pathlib import Path

import pytest

from inksim.config import Config


def test_config_loads_and_persists_values(tmp_path):
    path = tmp_path / "config.toml"
    config = Config(path)
    config.set("last_directory", "/tmp/designs")
    config.set("view", {"background_color": [10, 20, 30]})

    config2 = Config(path)
    assert config2.get("last_directory") == "/tmp/designs"
    assert config2.get("view") == {"background_color": [10, 20, 30]}


def test_config_get_returns_default_for_missing_key(tmp_path):
    config = Config(tmp_path / "config.toml")
    assert config.get("missing", "default") == "default"


def test_config_set_values_updates_multiple_keys(tmp_path):
    path = tmp_path / "config.toml"
    config = Config(path)
    config.set_values({"a": 1, "b": 2})

    config2 = Config(path)
    assert config2.get("a") == 1
    assert config2.get("b") == 2


def test_config_merge_preserves_sibling_keys(tmp_path):
    path = tmp_path / "config.toml"
    config = Config(path)
    config.set("display_calibration", {"default": 3.5, "HDMI-1": 4.0})
    config.merge_data({"display_calibration": {"default": 5.0}})

    config2 = Config(path)
    calibration = config2.get("display_calibration")
    assert calibration["default"] == 5.0
    assert calibration["HDMI-1"] == 4.0


def test_config_as_text_and_load_text(tmp_path):
    path = tmp_path / "config.toml"
    config = Config(path)
    config.set("answer", 42)
    text = config.as_text()
    assert "answer = 42" in text

    config.load_text("answer = 7\n")
    assert config.get("answer") == 7


def test_config_anonymizes_home_paths_in_nested_values(tmp_path):
    path = tmp_path / "config.toml"
    home_path = Path.home() / "tools" / "uvr"
    path.write_text(f"legacy_path = {json.dumps(str(home_path))}\n", encoding="utf-8")
    config = Config(path)
    portable_path = f"~/{home_path.relative_to(Path.home()).as_posix()}"
    assert config.get("legacy_path") == portable_path
    assert str(home_path) in path.read_text(encoding="utf-8")

    config.save()
    assert str(Path.home()) not in path.read_text(encoding="utf-8")

    config.set(
        "integration",
        {
            "interpreter": str(home_path),
            "error": f"Could not load {home_path}",
        },
    )

    expected = {"interpreter": portable_path, "error": f"Could not load {portable_path}"}
    assert config.get("integration") == expected
    assert Config(path).get("integration") == expected
    assert str(Path.home()) not in path.read_text(encoding="utf-8")
    assert str(Path.home()) not in config.as_text()


def test_config_defers_home_path_migration_until_write(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    home_path = Path.home() / "tools" / "uvr"
    original = f"legacy_path = {json.dumps(str(home_path))}\n"
    path.write_text(original, encoding="utf-8")

    def fail_lock(*_args, **_kwargs):
        raise PermissionError("config directory is not writable")

    monkeypatch.setattr("inksim.config.FileLock.acquire", fail_lock)

    config = Config(path)

    assert config.get("legacy_path") == "~/tools/uvr"
    assert path.read_text(encoding="utf-8") == original


def test_config_read_error_does_not_overwrite_existing_values(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    original = 'answer = 41\npreserve = "yes"\n'
    path.write_text(original, encoding="utf-8")
    config = Config(path)
    original_open = Path.open

    def fail_config_read(self, *args, **kwargs):
        if self == path:
            raise PermissionError("config file cannot be read")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_config_read)

    with pytest.raises(PermissionError, match="config file cannot be read"):
        config.set("answer", 42)

    monkeypatch.setattr(Path, "open", original_open)
    assert path.read_text(encoding="utf-8") == original


def test_config_load_text_rejects_invalid_toml(tmp_path):
    config = Config(tmp_path / "config.toml")
    with pytest.raises(ValueError, match="Invalid TOML"):
        config.load_text("[[not valid")


def test_config_update_is_atomic_across_instances(tmp_path):
    path = tmp_path / "config.toml"
    config = Config(path)
    config.set("counter", 0)

    errors = []

    def increment():
        try:
            cfg = Config(path)
            cfg.update("counter", lambda value: (value or 0) + 1)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=increment) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    final = Config(path).get("counter")
    assert final == 10


def test_config_does_not_write_until_save(tmp_path):
    path = tmp_path / "config.toml"
    config = Config(path)
    config._data["answer"] = 42
    assert not path.exists()


def test_config_keeps_pending_values_when_save_fails(tmp_path, monkeypatch):
    from inksim import config as config_module

    path = tmp_path / "config.toml"
    config = Config(path)
    original_dump = config_module.tomli_w.dump

    def fail_dump(*_args, **_kwargs):
        raise OSError("simulated write failure")

    monkeypatch.setattr("inksim.config.tomli_w.dump", fail_dump)
    with pytest.raises(OSError, match="simulated write failure"):
        config.set("answer", 42)

    monkeypatch.setattr("inksim.config.tomli_w.dump", original_dump)
    config.save()

    assert Config(path).get("answer") == 42


def test_config_corrupt_file_is_ignored(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("this is not valid toml", encoding="utf-8")
    config = Config(path)
    assert config.get("answer", "default") == "default"


def test_config_lock_file_is_created_next_to_config(tmp_path):
    path = tmp_path / "config.toml"
    config = Config(path)
    config.set("x", 1)
    assert config._lock_path == path.parent / "config.toml.lock"
    assert config._lock_path.exists()


def test_stale_instance_does_not_roll_back_newer_values(tmp_path):
    """A long-lived window config must not undo a dialog's fresh settings."""
    from inksim.config import Config

    path = tmp_path / "config.toml"
    window_config = Config(path)
    window_config.set("open_dialog_icon_size", 96)

    dialog_config = Config(path)
    dialog_config.set("open_dialog_icon_size", 140)
    dialog_config.set("open_dialog_view", "icons")

    # The main window writes something else later; its snapshot still holds 96.
    window_config.set("last_directory", "~/brother")

    stored = Config(path)
    assert stored.get("open_dialog_icon_size") == 140
    assert stored.get("open_dialog_view") == "icons"
    assert stored.get("last_directory") == "~/brother"
