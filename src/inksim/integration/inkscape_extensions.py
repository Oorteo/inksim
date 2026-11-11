# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Install InkSim's Inkscape extensions without removing user files."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
import tempfile
import xml.etree.ElementTree as ET
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
class InstallPlan:
    """A snapshot of the files and user confirmation needed for an install."""

    destination: Path
    launcher: Path
    files: dict[str, bytes]
    replace_files: tuple[str, ...]
    newly_discovered_files: tuple[str, ...]
    preserved_files: tuple[str, ...]
    state: tuple[tuple[str, str], ...]

    @property
    def requires_confirmation(self) -> bool:
        return bool(self.replace_files or self.newly_discovered_files)


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
    for name, content in files.items():
        path = destination / name
        _reject_symlink_parents(destination, path)
        if not path.exists():
            continue
        if path.is_symlink() or not path.is_file():
            raise InstallSafetyError(f"Refusing to replace a non-regular file: {path}")
        current_hash = _managed_hash(name, path.read_bytes())
        expected_hash = _managed_hash(name, content)
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
