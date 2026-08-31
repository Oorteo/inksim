"""Tests for the TOML-backed Config module."""

import os
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
