# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Install InkSim's Inkscape extensions without removing user files."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from xml.sax.saxutils import escape as escape_xml_text

INSTALL_DIRECTORY = "inksim"
MANIFEST_NAME = ".inksim-install.json"
_LAUNCHER_TOKEN = "__INKSIM_EXECUTABLE__"
_MANIFEST_VERSION = 1
_ASSET_DIRECTORY = Path(__file__).resolve().parents[1] / "assets" / "inkscape"


class InstallSafetyError(RuntimeError):
    """Raised when an existing extension directory cannot be safely updated."""


@dataclass(frozen=True)
class InstalledInkSimExtension:
    """A discovered InkSim extension directory and whether it is user-managed."""

    path: Path
    user_install: bool


@dataclass(frozen=True)
class InstallPlan:
    """A snapshot of the files and user confirmation needed for an install."""

    destination: Path
    launcher: Path
    files: dict[str, bytes]
    replace_files: tuple[str, ...]
    newly_discovered_files: tuple[str, ...]
    preserved_files: tuple[str, ...]
    update_files: tuple[str, ...]
    command_changed: bool
    state: tuple[tuple[str, str], ...]

    @property
    def requires_confirmation(self) -> bool:
        return bool(self.replace_files or self.newly_discovered_files)

    @property
    def update_required(self) -> bool:
        return bool(self.update_files or self.command_changed)


def find_installed_inksim_extensions(
    extension_roots: Sequence[tuple[Path, bool]],
) -> tuple[InstalledInkSimExtension, ...]:
    """Find InkSim extension directories in Inkscape's user and system roots."""
    found: dict[Path, bool] = {}
    for extension_root, user_install in extension_roots:
        root = extension_root.expanduser().resolve()
        if not root.exists():
            continue
        if not root.is_dir():
            raise InstallSafetyError(f"Extension root is not a directory: {root}")
        try:
            children = sorted(root.iterdir())
        except OSError as error:
            raise InstallSafetyError(
                f"Could not inspect extension directory {root}: {error}"
            ) from error
        for child in children:
            if child.is_symlink() or not child.is_dir() or not _is_inksim_extension(child):
                continue
            resolved = child.resolve()
            found[resolved] = found.get(resolved, False) or user_install
    return tuple(
        InstalledInkSimExtension(path, found[path])
        for path in sorted(found, key=lambda item: os.path.normcase(str(item)))
    )


def list_inksim_extension_files(directory: Path) -> tuple[str, ...]:
    """List regular files and symbolic links contained in an extension folder."""
    if directory.is_symlink() or not directory.is_dir():
        raise InstallSafetyError(f"Not a safe InkSim extension directory: {directory}")
    entries: list[str] = []
    for root, dirs, files in os.walk(directory, followlinks=False):
        root_path = Path(root)
        for name in list(dirs):
            path = root_path / name
            if path.is_symlink():
                dirs.remove(name)
                entries.append(f"{path.relative_to(directory).as_posix()} [symbolic link]")
        for name in files:
            path = root_path / name
            suffix = " [symbolic link]" if path.is_symlink() else ""
            entries.append(f"{path.relative_to(directory).as_posix()}{suffix}")
    return tuple(sorted(entries))


def remove_old_inksim_extension(
    directory: Path,
    user_extension_root: Path,
    *,
    confirmed: bool = False,
) -> None:
    """Remove a confirmed non-canonical InkSim folder inside the user extension root."""
    if not confirmed:
        raise InstallSafetyError("Removing an old extension folder requires user confirmation.")
    if directory.is_symlink():
        raise InstallSafetyError(f"Refusing to remove a symbolic link: {directory}")

    root = user_extension_root.expanduser().resolve(strict=True)
    target = directory.expanduser().resolve(strict=True)
    if target.parent != root:
        raise InstallSafetyError(
            f"Refusing to remove a folder outside the user extension root: {target}"
        )
    canonical = (root / INSTALL_DIRECTORY).resolve()
    if target == canonical:
        raise InstallSafetyError(
            f"Refusing to remove the current InkSim extension folder: {target}"
        )
    if not _is_inksim_extension(target):
        raise InstallSafetyError(f"Folder is not a recognized InkSim extension: {target}")

    shutil.rmtree(target)


def resolve_inksim_launcher() -> Path:
    """Find the InkSim command belonging to the currently running environment."""
    candidates = [Path(sys.argv[0]).expanduser()]
    executable_dir = "Scripts" if os.name == "nt" else "bin"
    suffixes = (".exe", "") if os.name == "nt" else ("",)
    candidates.extend(
        Path(sys.prefix) / executable_dir / f"{name}{suffix}"
        for name in ("inksim", "inksim-gui")
        for suffix in suffixes
    )

    for candidate in candidates:
        if candidate.name.lower() not in {
            "inksim",
            "inksim.exe",
            "inksim-gui",
            "inksim-gui.exe",
        }:
            continue
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        if resolved.is_file() and (os.name == "nt" or os.access(resolved, os.X_OK)):
            return resolved
    raise FileNotFoundError("Could not find the InkSim launcher for the current environment.")


def prepare_install(extension_directory: Path, launcher: Path) -> InstallPlan:
    """Inspect an installation and produce a safe plan without writing files."""
    resolved_launcher = launcher.expanduser().resolve(strict=True)
    if not resolved_launcher.is_file():
        raise FileNotFoundError(f"InkSim launcher is not a file: {resolved_launcher}")

    destination = extension_directory.expanduser().resolve() / INSTALL_DIRECTORY
    if destination.is_symlink():
        raise InstallSafetyError(f"Refusing to install through a symbolic link: {destination}")
    if destination.exists() and not destination.is_dir():
        raise InstallSafetyError(f"Extension path is not a directory: {destination}")

    files = _load_assets(resolved_launcher)
    actual_state = _tree_state(destination)
    actual_files = {name for name, _digest in actual_state}
    expected_names = set(files)
    manifest_path = destination / MANIFEST_NAME
    if manifest_path.is_symlink():
        raise InstallSafetyError(f"Refusing to use a symbolic-link manifest: {manifest_path}")

    old_hashes: dict[str, str] = {}
    old_preserved: set[str] = set()
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise InstallSafetyError(
                f"Could not read the InkSim extension manifest: {error}"
            ) from error
        if not isinstance(manifest, dict) or manifest.get("format") != _MANIFEST_VERSION:
            raise InstallSafetyError("The InkSim extension manifest has an unsupported format.")
        stored_hashes = manifest.get("files")
        stored_preserved = manifest.get("preserved", [])
        if (
            not isinstance(stored_hashes, dict)
            or not all(
                isinstance(name, str) and isinstance(value, str)
                for name, value in stored_hashes.items()
            )
            or not isinstance(stored_preserved, list)
            or not all(_is_safe_relative_name(name) for name in stored_preserved)
        ):
            raise InstallSafetyError("The InkSim extension manifest is invalid.")
        old_hashes = stored_hashes
        old_preserved = set(stored_preserved)

    replace_files: list[str] = []
    update_files: list[str] = []
    command_changed = False
    for name, content in files.items():
        path = destination / name
        _reject_symlink_parents(destination, path)
        if not path.exists():
            update_files.append(name)
            continue
        if path.is_symlink() or not path.is_file():
            raise InstallSafetyError(f"Refusing to replace a non-regular file: {path}")
        current_content = path.read_bytes()
        current_hash = _managed_hash(name, current_content)
        expected_hash = _managed_hash(name, content)
        if current_hash != expected_hash:
            update_files.append(name)
        if name == "preview.inx":
            actual_command = _preview_command(current_content)
            expected_command = _preview_command(content)
            command_changed = (
                actual_command is not None
                and expected_command is not None
                and actual_command != expected_command
            )
        if current_hash == expected_hash:
            continue
        if current_hash != old_hashes.get(name):
            replace_files.append(name)

    unknown_files = actual_files - expected_names - {MANIFEST_NAME}
    preserved_files = tuple(sorted(unknown_files))
    newly_discovered_files = tuple(sorted(unknown_files - old_preserved))
    return InstallPlan(
        destination=destination,
        launcher=resolved_launcher,
        files=files,
        replace_files=tuple(sorted(replace_files)),
        newly_discovered_files=newly_discovered_files,
        preserved_files=preserved_files,
        update_files=tuple(sorted(update_files)),
        command_changed=command_changed,
        state=actual_state,
    )


def install_extension(plan: InstallPlan, *, confirmed: bool = False) -> Path:
    """Apply a prepared plan, retaining unknown files and refusing stale plans."""
    if plan.requires_confirmation and not confirmed:
        raise InstallSafetyError("This installation requires explicit user confirmation.")
    if _tree_state(plan.destination) != plan.state:
        raise InstallSafetyError(
            "The extension directory changed; inspect it again before updating."
        )

    plan.destination.mkdir(parents=True, exist_ok=True)
    for name, content in plan.files.items():
        path = plan.destination / name
        _reject_symlink_parents(plan.destination, path)
        if path.is_symlink():
            raise InstallSafetyError(f"Refusing to replace a symbolic link: {path}")
        _atomic_write(path, content)

    manifest = {
        "format": _MANIFEST_VERSION,
        "files": {name: _managed_hash(name, content) for name, content in plan.files.items()},
        "preserved": list(plan.preserved_files),
    }
    _atomic_write(
        plan.destination / MANIFEST_NAME,
        (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    return plan.destination


def _load_assets(launcher: Path) -> dict[str, bytes]:
    try:
        assets = {
            path.relative_to(_ASSET_DIRECTORY).as_posix(): path.read_bytes()
            for path in _ASSET_DIRECTORY.rglob("*")
            if path.is_file()
        }
    except OSError as error:
        raise InstallSafetyError(f"Could not read packaged Inkscape extensions: {error}") from error
    if not assets:
        raise InstallSafetyError("No packaged Inkscape extension files were found.")

    preview_name = "preview.inx"
    if preview_name not in assets:
        raise InstallSafetyError("The packaged preview.inx file is missing.")
    assets[preview_name] = assets[preview_name].replace(
        _LAUNCHER_TOKEN.encode("ascii"),
        escape_xml_text(str(launcher)).encode("utf-8"),
    )
    if _LAUNCHER_TOKEN.encode("ascii") in assets[preview_name]:
        raise InstallSafetyError("The preview.inx launcher placeholder was not replaced.")
    return dict(sorted(assets.items()))


def _is_inksim_extension(directory: Path) -> bool:
    manifest_path = directory / MANIFEST_NAME
    if manifest_path.is_file() and not manifest_path.is_symlink():
        return True

    inx_files = list(directory.glob("*.inx")) + list((directory / "inx").glob("*.inx"))
    for inx_path in inx_files:
        if inx_path.is_symlink() or not inx_path.is_file():
            continue
        try:
            root = ET.parse(inx_path).getroot()
        except (OSError, ET.ParseError):
            continue
        for node in root.iter():
            if node.tag.rsplit("}", 1)[-1] == "id" and node.text:
                extension_id = node.text.strip().lower()
                if extension_id.startswith(("oorteo.inksim.", "org.inksim.")):
                    return True
    return False


def _managed_hash(name: str, content: bytes) -> str:
    if name == "preview.inx":
        try:
            root = ET.fromstring(content)
        except ET.ParseError:
            pass
        else:
            commands = [node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "command"]
            if len(commands) == 1:
                commands[0].text = _LAUNCHER_TOKEN
                content = ET.tostring(root, encoding="utf-8")
    return hashlib.sha256(content).hexdigest()


def _preview_command(content: bytes) -> str | None:
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return None
    commands = [node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "command"]
    if len(commands) != 1:
        return None
    return commands[0].text


def _tree_state(directory: Path) -> tuple[tuple[str, str], ...]:
    if not directory.exists():
        return ()
    if directory.is_symlink() or not directory.is_dir():
        raise InstallSafetyError(f"Extension path is not a safe directory: {directory}")

    entries: list[tuple[str, str]] = []
    for root, dirs, files in os.walk(directory, followlinks=False):
        root_path = Path(root)
        for name in list(dirs):
            path = root_path / name
            if path.is_symlink():
                dirs.remove(name)
                entries.append(
                    (path.relative_to(directory).as_posix(), f"symlink:{os.readlink(path)}")
                )
        for name in files:
            path = root_path / name
            relative = path.relative_to(directory).as_posix()
            if path.is_symlink():
                entries.append((relative, f"symlink:{os.readlink(path)}"))
            else:
                entries.append((relative, hashlib.sha256(path.read_bytes()).hexdigest()))
    return tuple(sorted(entries))


def _reject_symlink_parents(destination: Path, path: Path) -> None:
    relative = path.relative_to(destination)
    current = destination
    for part in relative.parts[:-1]:
        current /= part
        if current.is_symlink():
            raise InstallSafetyError(f"Refusing to write through a symbolic link: {current}")


def _is_safe_relative_name(name: object) -> bool:
    if not isinstance(name, str):
        return False
    path = PurePosixPath(name)
    return bool(name) and not path.is_absolute() and ".." not in path.parts


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary_path, stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644)
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
