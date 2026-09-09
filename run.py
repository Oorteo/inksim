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
TASKS = {
    "i": ("install dev environment", ["uv sync --all-groups"]),
    "t": ("run tests with coverage", ["uv run poe test"]),
    "l": ("run linter", ["uv run poe lint"]),
    "f": ("format source files", ["uv run poe format"]),
    "c": ("run static type checker", ["uv run poe typecheck"]),
    "k": ("lint + typecheck", ["uv run poe check"]),
    "x": ("auto-fix lint issues", ["uv run poe fix"]),
    "h": ("install git pre-commit hooks", ["uv run poe install-hooks"]),
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
            choice = input("Choose task [i/t/l/f/c/k/x/h/q]: ").strip().lower()
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
