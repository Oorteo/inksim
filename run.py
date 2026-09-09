#!/usr/bin/env uvr
"""Interactive task menu for InkSim development.

This script works on any OS as long as `uv` is available.
Run with: python run.py
"""

import subprocess
import sys
from pathlib import Path

# Root of the project (where this file lives)
ROOT = Path(__file__).resolve().parent

# Available tasks: key -> (description, list of shell commands).
# Ordered by speed/frequency: quick style checks first, expensive tests later,
# one-off setup tasks last.
TASKS = {
    "1": ("lint + typecheck", ["uv run poe check"]),
    "2": ("run linter", ["uv run poe lint"]),
    "3": ("run type checker", ["uv run poe typecheck"]),
    "4": ("format source files", ["uv run poe format"]),
    "5": ("preview auto-fixes", ["uv run ruff check . --show-fixes --diff"]),
    "6": ("auto-fix lint issues", ["uv run poe fix"]),
    "7": ("install git pre-commit hooks", ["uv run poe install-hooks"]),
    "8": ("install dev environment", ["uv sync --all-groups"]),
    "9": ("run tests", ["uv run poe test"]),
    "q": ("quit", None),
}


def print_menu() -> None:
    print()
    print("InkSim development menu")
    print("=" * 55)
    for key, (name, commands) in TASKS.items():
        if commands is None:
            print(f"  {key}: {name}")
        elif len(commands) == 1:
            print(f"  {key}: {name:<35} -> {commands[0]}")
        else:
            print(f"  {key}: {name}")
            for command in commands:
                print(f"      -> {command}")
    print()


def run_command(command: str) -> int:
    print(f"\n> {command}\n")
    return subprocess.run(command, shell=True, cwd=ROOT).returncode


def run_task(key: str) -> int:
    _, commands = TASKS[key]
    if commands is None:
        print("Bye.")
        return 0

    for command in commands:
        code = run_command(command)
        if code != 0:
            return code
    return 0


def main() -> int:
    if len(sys.argv) > 1:
        key = sys.argv[1]
        if key not in TASKS:
            print(f"Unknown task: {key}")
            print_menu()
            return 1
        return run_task(key)

    while True:
        print_menu()
        try:
            choice = input("Choose task [1-9/q]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            return 0

        if choice == "q":
            print("Bye.")
            return 0

        if choice not in TASKS:
            print("Invalid choice, try again.")
            continue

        run_task(choice)


if __name__ == "__main__":
    sys.exit(main())
