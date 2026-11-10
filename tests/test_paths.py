# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import Path

from inksim.paths import _sanitize_path


def test_sanitize_path_does_not_duplicate_home_for_portable_path():
    path = "~/local/Sources/inkscape/inkstitch/inkstitch/inx"

    expected = f"~/{Path(path).expanduser().resolve().relative_to(Path.home()).as_posix()}"
    assert _sanitize_path(path) == expected
