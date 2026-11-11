# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from inksim.integration.inkscape_extensions import (
    InstallSafetyError,
    install_extension,
    prepare_install,
)


def _launcher(tmp_path: Path) -> Path:
    launcher = tmp_path / "venv & branch" / "bin" / "inksim"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("#!/bin/sh\n", encoding="utf-8")
    launcher.chmod(0o755)
    return launcher


def test_install_renders_active_launcher_and_installs_assets(tmp_path):
    launcher = _launcher(tmp_path)
    extension_directory = tmp_path / "extensions"

    plan = prepare_install(extension_directory, launcher)
    destination = install_extension(plan)
    preview = (destination / "preview.inx").read_text(encoding="utf-8")
    root = ET.fromstring(preview)
    command = next(node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "command")

    assert command.text == str(launcher.resolve())
    assert "__INKSIM_EXECUTABLE__" not in preview
    assert (destination / "about.inx").is_file()
    assert (destination / "scripts" / "about.py").is_file()


def test_launcher_change_does_not_count_as_user_edit(tmp_path):
    first_launcher = _launcher(tmp_path)
    extension_directory = tmp_path / "extensions"
    install_extension(prepare_install(extension_directory, first_launcher))

    second_launcher = tmp_path / "other & venv" / "bin" / "inksim"
    second_launcher.parent.mkdir(parents=True)
    second_launcher.write_text("#!/bin/sh\n", encoding="utf-8")
    second_launcher.chmod(0o755)
    plan = prepare_install(extension_directory, second_launcher)

    assert not plan.requires_confirmation
    install_extension(plan)
    root = ET.parse(plan.destination / "preview.inx").getroot()
    command = next(node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "command")

    assert command.text == str(second_launcher.resolve())


def test_modified_managed_file_requires_confirmation(tmp_path):
    launcher = _launcher(tmp_path)
    extension_directory = tmp_path / "extensions"
    destination = install_extension(prepare_install(extension_directory, launcher))
    (destination / "about.inx").write_text("user change", encoding="utf-8")

    plan = prepare_install(extension_directory, launcher)

    assert plan.replace_files == ("about.inx",)
    assert plan.requires_confirmation
    with pytest.raises(InstallSafetyError, match="explicit user confirmation"):
        install_extension(plan)
    install_extension(plan, confirmed=True)
    assert "About InkSim" in (destination / "about.inx").read_text(encoding="utf-8")


def test_unknown_files_are_preserved_and_reported_once(tmp_path):
    launcher = _launcher(tmp_path)
    extension_directory = tmp_path / "extensions"
    destination = extension_directory / "inksim"
    destination.mkdir(parents=True)
    extra_file = destination / "development.txt"
    extra_file.write_text("keep me", encoding="utf-8")

    plan = prepare_install(extension_directory, launcher)

    assert plan.newly_discovered_files == ("development.txt",)
    install_extension(plan, confirmed=True)
    assert extra_file.read_text(encoding="utf-8") == "keep me"

    second_plan = prepare_install(extension_directory, launcher)
    assert not second_plan.requires_confirmation


def test_install_refuses_symbolic_link_target(tmp_path):
    launcher = _launcher(tmp_path)
    extension_directory = tmp_path / "extensions"
    external_directory = tmp_path / "external"
    external_directory.mkdir()
    extension_directory.mkdir()
    try:
        (extension_directory / "inksim").symlink_to(external_directory, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"Cannot create a symbolic link on this platform: {error}")

    with pytest.raises(InstallSafetyError, match="symbolic link"):
        prepare_install(extension_directory, launcher)
