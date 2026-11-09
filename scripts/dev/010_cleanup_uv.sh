#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Remove generated Python, test, lint, and packaging files.
set -euo pipefail

usage() {
    printf 'Usage: %s [-h|--help] [-y|--yes] [--uv-venv|--uv]\n' "$0"
    printf '  -h, --help     Show this help and exit.\n'
    printf '  Interactive by default: choose 1, 2, or q.\n'
    printf '  1              Remove generated artifacts outside .venv.\n'
    printf '  2              Also remove .venv, uv.lock, and .python-version.\n'
    printf '  -y, --yes      Skip the prompt and choose 1, or 2 with --uv.\n'
    printf '  --uv-venv, --uv  Include UV files when using --yes.\n'
}

ASSUME_YES=false
INCLUDE_UV_VENV=false
for argument in "$@"; do
    case "$argument" in
    -y | --yes) ASSUME_YES=true ;;
    --uv-venv | --uv) INCLUDE_UV_VENV=true ;;
    -h | --help)
        usage
        exit 0
        ;;
    *)
        usage >&2
        exit 1
        ;;
    esac
done

# Resolve the script location even when this script was started through a symlink.
SOURCE="${BASH_SOURCE[0]}"
# Resolve symlinks portably; this is the Bash equivalent of readlink -f.
while [[ -L "$SOURCE" ]]; do
    SCRIPT_DIR="$(cd -P "$(dirname "$SOURCE")" >/dev/null 2>&1 && pwd)"
    SOURCE="$(readlink "$SOURCE")"
    [[ "$SOURCE" = /* ]] || SOURCE="$SCRIPT_DIR/$SOURCE"
done
SCRIPT_DIR="$(cd -P "$(dirname "$SOURCE")" >/dev/null 2>&1 && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." >/dev/null 2>&1 && pwd)"

[[ -f "$PROJECT_ROOT/pyproject.toml" ]] || {
    printf 'Could not find pyproject.toml above script: %s\n' "$PROJECT_ROOT" >&2
    exit 1
}

declare -a ARTIFACT_TARGETS=()
# Find generated artifacts outside .venv; the virtual environment is opt-in.
while IFS= read -r -d '' target; do
    ARTIFACT_TARGETS+=("$target")
done < <(
    find "$PROJECT_ROOT" \
        -path "$PROJECT_ROOT/.git" -prune -o \
        -path "$PROJECT_ROOT/.venv" -prune -o \
        -type d \( \
        -name '__pycache__' -o \
        -name '.pytest_cache' -o \
        -name '.mypy_cache' -o \
        -name '.ruff_cache' -o \
        -name '.tox' -o \
        -name '.nox' -o \
        -name 'build' -o \
        -name 'dist' -o \
        -name '*.egg-info' \
        \) -print0 -prune -o \
        -type f \( \
        -name '*.pyc' -o \
        -name '*.pyo' -o \
        -name '.coverage' \
        \) -print0
)

declare -a UV_TARGETS=()
for protected_path in .venv uv.lock .python-version; do
    [[ -e "$PROJECT_ROOT/$protected_path" ]] && UV_TARGETS+=("$PROJECT_ROOT/$protected_path")
done

print_targets() {
    if (($# == 0)); then
        printf '    (none)\n'
        return 0
    fi
    local target
    for target in "$@"; do
        printf '    %s\n' "${target#"$PROJECT_ROOT"/}"
    done
}

printf '\nCleanup plan for: %s\n' "$PROJECT_ROOT"
printf '  [1] Generated artifacts outside .venv (%d path(s)):\n' "${#ARTIFACT_TARGETS[@]}"
print_targets ${ARTIFACT_TARGETS[@]+"${ARTIFACT_TARGETS[@]}"}
printf '  [2] UV targets, removed together with [1] (%d path(s)):\n' "${#UV_TARGETS[@]}"
print_targets ${UV_TARGETS[@]+"${UV_TARGETS[@]}"}

choice=1
if [[ "$ASSUME_YES" != true ]]; then
    printf '\nRemove [1] artifacts only, [2] artifacts + UV targets, [q] quit? [1/2/q] '
    read -r answer || answer=q
    case "$answer" in
    1 | 2) choice=$answer ;;
    *)
        printf 'Cleanup cancelled.\n'
        exit 0
        ;;
    esac
elif [[ "$INCLUDE_UV_VENV" == true ]]; then
    choice=2
fi

declare -a TARGETS=()
if ((${#ARTIFACT_TARGETS[@]} > 0)); then
    TARGETS+=("${ARTIFACT_TARGETS[@]}")
fi
if [[ "$choice" == 2 ]] && ((${#UV_TARGETS[@]} > 0)); then
    TARGETS+=("${UV_TARGETS[@]}")
fi

if ((${#TARGETS[@]} == 0)); then
    printf '\nNothing to remove.\n'
    exit 0
fi

printf '\nRemoving %d path(s) ...\n' "${#TARGETS[@]}"

for target in "${TARGETS[@]}"; do
    rm -rf -- "$target"
done

printf 'Cleanup complete. Removed %d path(s).\n' "${#TARGETS[@]}"
