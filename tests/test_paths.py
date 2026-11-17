# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import Path

import pytest

from inksim.paths import _sanitize_path, _unsanitize_path


def test_sanitize_path_does_not_duplicate_home_for_portable_path():
    path = "~/local/Sources/inkscape/inkstitch/inkstitch/inx"

    expected = (
        f"~/{Path(path).expanduser().resolve().relative_to(Path.home().resolve()).as_posix()}"
    )
    assert _sanitize_path(path) == expected


def test_sanitize_path_handles_a_symlinked_home(tmp_path, monkeypatch):
    real_home = tmp_path / "real-home"
    real_home.mkdir()
    home_link = tmp_path / "home"
    try:
        home_link.symlink_to(real_home, target_is_directory=True)
    except OSError as ex:
        pytest.skip(f"Cannot create symbolic links here: {ex}")
    monkeypatch.setattr(Path, "home", lambda: home_link)

    assert _sanitize_path(real_home / "designs") == "~/designs"


def test_unsanitize_path_expands_standalone_home_marker():
    assert _unsanitize_path("~") == str(Path.home())
