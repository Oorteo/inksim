# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for PyPI update version ordering."""

import pytest

from inksim.update_check import _latest_stable_version, is_newer


@pytest.mark.parametrize(
    ("latest", "current", "expected"),
    [
        ("0.6.0", "0.6.0rc1", True),
        ("0.6.0rc1", "0.6.0", False),
        ("0.6.0rc2", "0.6.0rc1", True),
        ("0.6.0rc10", "0.6.0rc2", True),
        ("0.6.1rc1", "0.6.0", True),
        ("0.6.0-rc.1", "0.6.0rc1", False),
        ("0.6.0", "0.6.0", False),
    ],
)
def test_is_newer_orders_release_candidates(latest, current, expected):
    assert is_newer(latest, current) is expected


def test_latest_stable_version_ignores_release_candidates():
    assert _latest_stable_version(["0.6.0rc1", "0.5.4", "0.6.0rc2", "0.5.10", "0.6.0"]) == "0.6.0"
