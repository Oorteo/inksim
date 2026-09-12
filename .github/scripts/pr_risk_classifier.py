#!/usr/bin/env python3
"""Classify a pull request as low, medium or high risk for auto-merge.

Rules:
- low: only documentation, tests, i18n, small safe refactors, dependency bumps
       that pass CI and do not touch protected paths.
- medium: any change in src/inksim/render or src/inksim/gui that is not purely
          additive tests/docs.
- high: protected paths (CODEOWNERS paths), architectural changes, new runtime
        dependencies, workflow changes.

Outputs a GitHub Actions step summary and sets an output named ``risk``.
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Paths that only the repository owner may change.
PROTECTED_PREFIXES = [
    ".github/",
    "LICENSE",
    "CLA.md",
    "CONTRIBUTING.md",
    "pyproject.toml",
    "src/inksim/cli.py",
    "src/inksim/__main__.py",
    "src/inksim/__init__.py",
    "src/inksim/constants.py",
    "src/inksim/config.py",
]

SENSITIVE_MODULES = [
    "src/inksim/render/",
    "src/inksim/gui/",
]


def github_api(path: str, token: str) -> dict:
    url = f"https://api.github.com{path}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read())


def classify(files: list[str]) -> str:
    has_protected = any(
        any(f == prefix or f.startswith(prefix) for prefix in PROTECTED_PREFIXES) for f in files
    )
    has_sensitive = any(any(f.startswith(prefix) for prefix in SENSITIVE_MODULES) for f in files)
    only_docs = all(
        f.startswith(("docs/", "README", "CONTRIBUTING", "CLA"))
        or f.endswith((".md", ".rst", ".txt"))
        or f.startswith("tests/")
        or f.startswith("src/inksim/locales/")
        for f in files
    )

    if has_protected:
        return "high"
    if has_sensitive and not only_docs:
        return "medium"
    if only_docs or all(f.startswith("src/inksim/locales/") for f in files):
        return "low"
    return "medium"


def main() -> int:
    parser = argparse.ArgumentParser(description="PR risk classifier")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"))
    args = parser.parse_args()

    if not args.token:
        print("No GitHub token provided.")
        return 1

    data = github_api(f"/repos/{args.repo}/pulls/{args.pr}/files", args.token)
    filenames = [entry["filename"] for entry in data]
    risk = classify(filenames)

    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "a", encoding="utf-8") as fh:
            fh.write(f"## PR risk classification: **{risk}**\n\n")
            fh.write("Changed files:\n")
            for name in filenames:
                fh.write(f"- `{name}`\n")
            fh.write("\n")

    print(f"risk={risk}")
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as fh:
            fh.write(f"risk={risk}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
