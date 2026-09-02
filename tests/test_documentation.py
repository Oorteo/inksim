# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

import re
from pathlib import Path


SCRIPT_REFERENCE = re.compile(r"(?<![\w/.])(?:\./)?(scripts/[\w/.-]+)")


def test_documentation_references_existing_scripts():
    """Ensure script commands in the documentation point to real files."""
    repository_root = Path(__file__).resolve().parents[1]
    missing_references = []
    for document in (repository_root / "docs").rglob("*.md"):
        content = document.read_text(encoding="utf-8")
        for match in SCRIPT_REFERENCE.finditer(content):
            script_path = repository_root / match.group(1)
            if not script_path.is_file():
                missing_references.append(
                    f"{document.relative_to(repository_root)}: "
                    f"{match.group(1)}"
                )

    assert not missing_references, (
        "Documentation references missing scripts:\n"
        + "\n".join(missing_references)
    )