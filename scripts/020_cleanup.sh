#!/usr/bin/env bash
# Remove generated Python, test, lint, and packaging files.
set -euo pipefail

usage() {
    printf 'Usage: %s [--uv-venv|--uv] [-y|--yes]\n' "$0"
    printf '  --uv-venv, --uv  Also remove .venv, uv.lock, and .python-version.\n'
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
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd)"

[[ -f "$PROJECT_ROOT/pyproject.toml" ]] || {
    printf 'Could not find pyproject.toml above script: %s\n' "$PROJECT_ROOT" >&2
    exit 1
}

declare -a TARGETS=()
while IFS= read -r -d '' target; do
    TARGETS+=("$target")
done < <(
    find "$PROJECT_ROOT" \
        -path "$PROJECT_ROOT/.git" -prune -o \
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

if [[ "$INCLUDE_UV_VENV" == true ]]; then
    for protected_path in .venv uv.lock .python-version; do
        [[ -e "$PROJECT_ROOT/$protected_path" ]] && TARGETS+=("$PROJECT_ROOT/$protected_path")
    done
fi

printf '\nCleanup plan for: %s\n' "$PROJECT_ROOT"
if ((${#TARGETS[@]} == 0)); then
    printf '  Nothing to remove.\n'
    exit 0
fi
printf '  The following generated paths will be removed:\n'
for target in "${TARGETS[@]}"; do
    printf '    %s\n' "${target#"$PROJECT_ROOT"/}"
done
printf '  Total: %d path(s)\n' "${#TARGETS[@]}"

if [[ "$ASSUME_YES" != true ]]; then
    printf '\nContinue? [y/N] '
    read -r answer
    [[ "$answer" =~ ^[Yy]$ ]] || {
        printf 'Cleanup cancelled.\n'
        exit 0
    }
fi

for target in "${TARGETS[@]}"; do
    rm -rf -- "$target"
done

printf 'Cleanup complete. Removed %d path(s).\n' "${#TARGETS[@]}"
