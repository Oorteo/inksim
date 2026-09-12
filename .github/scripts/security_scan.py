#!/usr/bin/env python3
"""Security scanner for InkSim pull requests.

This script is intentionally simple and auditable. It does not rely on any
external API or secret beyond the source code itself. It fails the CI build
if suspicious patterns, hidden backdoor-like functions or unauthorised
project-identity changes are detected.

If a legitimate occurrence of a banned pattern is needed, mark it explicitly
with a comment containing ``# security:allowed`` on the same line.
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "inksim"

# Text patterns that are dangerous regardless of context.  AST-based checks
# below handle eval/exec/compile/__import__ more precisely so we do not flag
# harmless Qt ``.exec()`` or ``re.compile()`` calls.
TEXT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bos\.system\s*\("), "os.system() call"),
    (re.compile(r"\bos\.popen\s*\("), "os.popen() call"),
    (re.compile(r"subprocess\.\w+\s*\([^)]*shell\s*=\s*True"), "subprocess with shell=True"),
    (re.compile(r"pickle\.loads?\s*\("), "pickle deserialization"),
    (re.compile(r"marshal\.loads?\s*\("), "marshal deserialization"),
    (re.compile(r"yaml\.load\s*\("), "yaml.load() without SafeLoader"),
    (re.compile(r"getattr\s*\([^)]*__globals__"), "access to __globals__"),
    (re.compile(r"base64\.b64decode\s*\([^)]*\)\s*\."), "chained b64decode execution"),
    (re.compile(r"input\s*\(\s*\)\s*\.eval"), "input chained to eval"),
    (re.compile(r"\brequests\.post\s*\([^)]*\bdata\s*=\s*__import__"), "suspicious exfiltration"),
]

# Built-in calls that are dangerous when invoked as a bare name (not a method).
DANGEROUS_BUILTINS = {"eval", "exec", "compile", "__import__"}

# Module-qualified calls that are dangerous anywhere.
DANGEROUS_ATTRIBUTE_CALLS = {
    ("os", "system"),
    ("os", "popen"),
    ("pickle", "load"),
    ("pickle", "loads"),
    ("marshal", "load"),
    ("marshal", "loads"),
    ("yaml", "load"),
}


class Finding:
    def __init__(self, message: str) -> None:
        self.message = message


def run_bandit() -> tuple[bool, list[Finding]]:
    """Run bandit over the source tree."""
    result = subprocess.run(
        ["uv", "run", "bandit", "-r", str(SRC), "-f", "txt", "-ll"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.stdout:
        print("::group::bandit output")
        print(result.stdout)
        print("::endgroup::")
    if result.returncode != 0:
        return False, [Finding("bandit reported security issues")]
    return True, []


def grep_patterns() -> tuple[bool, list[Finding]]:
    """Scan for constructs that look like backdoors.

    Combines AST-based detection (eval/exec/compile/__import__ as bare
    built-ins) with text-based detection for dangerous module-qualified calls
    and suspicious idioms.  This avoids false positives from Qt ``.exec()``
    and ``re.compile()``.
    """
    findings: list[Finding] = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(ROOT)
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            findings.append(Finding(f"{rel}: syntax error {exc}"))
            continue

        # AST-based detection of dangerous built-in calls.
        lines = source.splitlines()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in DANGEROUS_BUILTINS:
                    line = lines[node.lineno - 1] if node.lineno else ""
                    if "# security:allowed" in line:
                        continue
                    findings.append(Finding(f"{rel}:{node.lineno}: {node.func.id}() built-in call"))

        # Text-based detection for dangerous idioms and module-qualified calls.
        for lineno, line in enumerate(source.splitlines(), start=1):
            if "# security:allowed" in line:
                continue
            for pattern, description in TEXT_PATTERNS:
                if pattern.search(line):
                    findings.append(Finding(f"{rel}:{lineno}: {description}: {line.strip()}"))

    return not findings, findings


def check_hidden_functions() -> tuple[bool, list[Finding]]:
    """Detect private functions that perform dangerous operations.

    A private function (single leading underscore) is allowed in normal GUI
    code, but if it calls eval/exec/compile/__import__, os.system/popen,
    pickle/marshal/yaml.load, or uses base64-decode chains, it is flagged for
    review.  The goal is to surface potential backdoors hidden in obscure
    helper methods.
    """
    findings: list[Finding] = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(ROOT)
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            findings.append(Finding(f"{rel}: syntax error {exc}"))
            continue

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name.startswith("__"):
                continue
            if not node.name.startswith("_"):
                continue

            dangerous = False
            lines = source.splitlines()
            for child in ast.walk(node):
                if not isinstance(child, ast.Call):
                    continue
                # Honour the same-line suppression comment.
                if child.lineno and "# security:allowed" in lines[child.lineno - 1]:
                    continue
                if isinstance(child.func, ast.Name) and child.func.id in DANGEROUS_BUILTINS:
                    dangerous = True
                elif (
                    isinstance(child.func, ast.Attribute)
                    and isinstance(child.func.value, ast.Name)
                    and (child.func.value.id, child.func.attr) in DANGEROUS_ATTRIBUTE_CALLS
                ):
                    dangerous = True
                elif isinstance(child.func, ast.Attribute):
                    # base64.b64decode(...) chained to another operation, e.g.
                    # eval(base64.b64decode(...)) or b64decode(...).decode().
                    if (
                        isinstance(child.func.value, ast.Call)
                        and isinstance(child.func.value.func, ast.Attribute)
                        and child.func.value.func.attr == "b64decode"
                    ):
                        dangerous = True
                    # subprocess.* with a literal shell=True keyword.
                    if child.func.attr in {"call", "run", "Popen", "check_output"} and any(
                        isinstance(kw, ast.keyword)
                        and kw.arg == "shell"
                        and isinstance(kw.value, ast.Constant)
                        and kw.value.value is True
                        for kw in child.keywords
                    ):
                        dangerous = True
            if dangerous:
                findings.append(
                    Finding(
                        f"{rel}:{node.lineno}: private function '{node.name}' "
                        "performs a dangerous operation and requires manual review"
                    )
                )
    return not findings, findings


def check_project_identity() -> tuple[bool, list[Finding]]:
    """Guard core project metadata that must stay stable."""
    findings: list[Finding] = []
    pyproject_path = ROOT / "pyproject.toml"
    if not pyproject_path.exists():
        findings.append(Finding("pyproject.toml is missing"))
        return False, findings

    try:
        with pyproject_path.open("rb") as fh:
            pyproject = tomllib.load(fh)
    except (tomllib.TOMLDecodeError, OSError) as exc:
        findings.append(Finding(f"pyproject.toml could not be parsed: {exc}"))
        return False, findings

    project = pyproject.get("project", {})
    expected = {
        "name": "inksim",
        "license.file": "LICENSE",
        "scripts.inksim": "inksim.cli:main",
        "gui-scripts.inksim-gui": "inksim.cli:main",
    }
    actual = {
        "name": project.get("name"),
        "license.file": (project.get("license") or {}).get("file"),
        "scripts.inksim": (project.get("scripts") or {}).get("inksim"),
        "gui-scripts.inksim-gui": (project.get("gui-scripts") or {}).get("inksim-gui"),
    }
    for key, want in expected.items():
        if actual[key] != want:
            findings.append(
                Finding(
                    f"pyproject.toml {key} must be {want!r} "
                    "(possible unauthorised project identity change)"
                )
            )

    return not findings, findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="InkSim security scan")
    parser.parse_args(argv)

    checks = [
        ("bandit", run_bandit),
        ("dangerous patterns", grep_patterns),
        ("hidden functions", check_hidden_functions),
        ("project identity", check_project_identity),
    ]

    all_ok = True
    for name, checker in checks:
        print(f"::group::{name}")
        ok, findings = checker()
        for finding in findings:
            print(finding.message)
        print("::endgroup::")
        if not ok:
            all_ok = False

    if not all_ok:
        print("Security scan failed.")
        return 1
    print("Security scan passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
