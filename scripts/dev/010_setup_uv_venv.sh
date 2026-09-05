#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Set up the project's uv environment on macOS, Linux,
# or Windows via Bash (Git Bash/WSL).
set -euo pipefail
#set -x

CLEAN_VENV=false
PYTHON_VERSION_ARG=""

for arg in "$@"; do
    case "$arg" in
    -y | --yes)
        CLEAN_VENV=true
        ;;
    --python=*)
        PYTHON_VERSION_ARG="${arg#*=}"
        ;;
    *)
        echo "Usage: $0 [-y|--yes] [--python=VERSION]" >&2
        echo "  -y, --yes       recreate the virtual environment without asking" >&2
        echo "  --python=VER    use the given Python version (default: env PYTHON_VERSION or 3.14)" >&2
        exit 1
        ;;
    esac
done

PYTHON_VERSION="${PYTHON_VERSION_ARG:-${PYTHON_VERSION:-3.14}}"

SOURCE="${BASH_SOURCE[0]}"
# Resolve symlinks portably; this is the Bash equivalent of readlink -f.
while [[ -L "$SOURCE" ]]; do
    SCRIPT_DIR="$(cd -P "$(dirname "$SOURCE")" >/dev/null 2>&1 && pwd)"
    SOURCE="$(readlink "$SOURCE")"
    [[ "$SOURCE" = /* ]] || SOURCE="$SCRIPT_DIR/$SOURCE"
done
SCRIPT_DIR="$(cd -P "$(dirname "$SOURCE")" >/dev/null 2>&1 && pwd)"
PYTHON_VERSION="${PYTHON_VERSION:-3.14}"

cd "$SCRIPT_DIR/../.."
VENV_PATH="$PWD/.venv"
UV_PATH="$(command -v uv || true)"
[[ -n "$UV_PATH" ]] || {
    echo "uv is required" >&2
    exit 1
}

printf '\nDetected configuration:\n'
printf '  Python:      %s\n' "$PYTHON_VERSION"
printf '  uv:          %s\n' "$UV_PATH"
printf '  Project:     %s\n' "$PWD"
printf '  Virtual env: %s\n' "$VENV_PATH"
printf '  Clean .venv: %s\n\n' "$CLEAN_VENV"

if [[ "$CLEAN_VENV" == true ]]; then
    echo "Removing virtual environment: $VENV_PATH"
    rm -rf "$VENV_PATH"
elif [[ -d "$VENV_PATH" ]]; then
    echo "Found virtual environment: $VENV_PATH"
    read -r -p "Set it up again? [y/N] " answer
    [[ "$answer" =~ ^[Yy]$ ]] || exit 0
else
    echo "Virtual environment will be created at: $VENV_PATH"
    read -r -p "Set up uv environment? [Y/n] " answer
    [[ "$answer" =~ ^[Nn]$ ]] && exit 0
fi

uv python pin "$PYTHON_VERSION"
uv sync
