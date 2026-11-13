# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from inksim.integration.inkscape_extensions import (
    InstallSafetyError,
    find_installed_inksim_extensions,
    install_extension,
    list_inksim_extension_files,
    prepare_install,
    remove_old_inksim_extension,
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
    assert plan.update_required
    destination = install_extension(plan)
    preview = (destination / "preview.inx").read_text(encoding="utf-8")
    root = ET.fromstring(preview)
    command = next(node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "command")
    create_script = next(
        node
        for node in root.iter()
        if node.tag.rsplit("}", 1)[-1] == "param" and node.get("name") == "create_bash_script"
    )

    assert command.text == str(launcher.resolve())
    assert create_script.get("type") == "boolean"
    assert create_script.get("gui-hidden") == "true"
    assert create_script.text == "false"
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
    assert plan.update_required
    assert not plan.update_files
    assert plan.command_changed
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
    assert plan.update_required
    assert plan.update_files == ("about.inx",)
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


def test_find_and_remove_only_confirmed_old_inksim_extension(tmp_path):
    user_root = tmp_path / "user" / "extensions"
    system_root = tmp_path / "system" / "extensions"
    current = user_root / "inksim"
    old_copy = user_root / "inksim-old"
    system_copy = system_root / "inksim"
    unrelated = user_root / "my-extensions"
    for directory in (current, old_copy, system_copy, unrelated):
        directory.mkdir(parents=True)

    marker = current / ".inksim-install.json"
    marker.write_text('{"format": 1}', encoding="utf-8")
    (old_copy / "preview.inx").write_text(
        "<inkscape-extension><id>oorteo.inksim.preview</id></inkscape-extension>",
        encoding="utf-8",
    )
    (system_copy / "about.inx").write_text(
        "<inkscape-extension><id>org.inksim.about</id></inkscape-extension>",
        encoding="utf-8",
    )
    (unrelated / "about.inx").write_text(
        "<inkscape-extension><id>example.other.about</id></inkscape-extension>",
        encoding="utf-8",
    )

    installations = find_installed_inksim_extensions([(user_root, True), (system_root, False)])

    assert {item.path: item.user_install for item in installations} == {
        current.resolve(): True,
        old_copy.resolve(): True,
        system_copy.resolve(): False,
    }
    assert list_inksim_extension_files(old_copy) == ("preview.inx",)
    with pytest.raises(InstallSafetyError, match="user confirmation"):
        remove_old_inksim_extension(old_copy, user_root)
    with pytest.raises(InstallSafetyError, match="current InkSim"):
        remove_old_inksim_extension(current, user_root, confirmed=True)

    remove_old_inksim_extension(old_copy, user_root, confirmed=True)

    assert not old_copy.exists()
    assert current.exists()
    assert system_copy.exists()
