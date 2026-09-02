#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Create tar.gz archives from the last commit or tracked workspace files.
set -euo pipefail

usage() {
    printf 'Usage: %s [--commit|-c|--workspace|-w|--src|-s] [--py] [-y|--yes]\n' "$0"
    printf '  --commit, -c      Archive the last commit with git archive.\n'
    printf '  --workspace, -w   Archive all Git-tracked files in their workspace state.\n'
    printf '  --src, -s         Archive only Git-tracked files under src/.\n'
    printf '  --py              Include only Python source files (workspace/src only).\n'
    printf '  -y, --yes         Overwrite an existing archive without asking.\n'
}

mode=''
py_only=false
assume_yes=false
for argument in "$@"; do
    case "$argument" in
    --commit | -c | --workspace | -w | --src | -s)
        [[ -z "$mode" ]] || {
            usage >&2
            exit 1
        }
        case "$argument" in
        --commit | -c) mode=commit ;;
        --workspace | -w) mode=workspace ;;
        --src | -s) mode=src ;;
        esac
        ;;
    --py) py_only=true ;;
    -y | --yes) assume_yes=true ;;
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

SOURCE="${BASH_SOURCE[0]}"
# Resolve symlinks portably; this is the Bash equivalent of readlink -f.
while [[ -L "$SOURCE" ]]; do
    SCRIPT_DIR="$(cd -P "$(dirname "$SOURCE")" >/dev/null 2>&1 && pwd)"
    SOURCE="$(readlink "$SOURCE")"
    [[ "$SOURCE" = /* ]] || SOURCE="$SCRIPT_DIR/$SOURCE"
done
SCRIPT_DIR="$(cd -P "$(dirname "$SOURCE")" >/dev/null 2>&1 && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"
while [[ ! -f "$PROJECT_ROOT/pyproject.toml" && "$PROJECT_ROOT" != "/" ]]; do
    PROJECT_ROOT="$(cd -- "$PROJECT_ROOT/.." && pwd)"
done
# Ensure we land on the project root even if the script was invoked through a symlink.
PROJECT_ROOT="$(cd "$PROJECT_ROOT" && pwd)"
[[ -f "$PROJECT_ROOT/pyproject.toml" ]] || {
    printf 'Could not find pyproject.toml above %s.\n' "$SCRIPT_DIR" >&2
    exit 1
}

PROJECT_NAME="$(git -C "$PROJECT_ROOT" remote get-url origin 2>/dev/null |
    sed -E 's#.*/##; s#\.git$##' || true)"
PROJECT_NAME="${PROJECT_NAME:-$(basename "$PROJECT_ROOT")}"
LAST_COMMIT="$(git -C "$PROJECT_ROOT" rev-parse --short HEAD)"
OUTPUT_DIR="$(dirname "$PROJECT_ROOT")"

if [[ -z "$mode" ]]; then
    printf 'Select archive contents:\n'
    printf '  1) Last commit (git archive)\n'
    printf '  2) Tracked workspace files\n'
    printf '  3) Tracked Python workspace files only\n'
    printf '  4) Tracked src/ files only\n'
    printf '  5) Tracked Python src/ files only\n'
    printf 'Choice [1-5]: '
    read -r choice
    case "$choice" in
    1) mode=commit ;;
    2) mode=workspace ;;
    3)
        mode=workspace
        py_only=true
        ;;
    4) mode=src ;;
    5)
        mode=src
        py_only=true
        ;;
    *)
        printf 'Archive creation cancelled.\n'
        exit 0
        ;;
    esac
fi

if [[ "$py_only" == true && "$mode" == commit ]]; then
    printf 'Python-only filtering is available only for workspace and src archives.\n' >&2
    exit 1
fi

archive_suffix=''
[[ "$py_only" == true ]] && archive_suffix='-py'
case "$mode" in
commit) archive_name="${PROJECT_NAME}-commit-${LAST_COMMIT}.tar.gz" ;;
workspace) archive_name="${PROJECT_NAME}-workspace${archive_suffix}-${LAST_COMMIT}.tar.gz" ;;
src) archive_name="${PROJECT_NAME}-src${archive_suffix}-${LAST_COMMIT}.tar.gz" ;;
esac
ARCHIVE_PATH="$OUTPUT_DIR/$archive_name"

printf '\nArchive plan:\n'
printf '  Project: %s\n' "$PROJECT_ROOT"
printf '  Mode:    %s\n' "$mode"
printf '  Output:  %s\n' "$ARCHIVE_PATH"
case "$mode" in
commit) printf '  Source:  last commit %s via git archive\n' "$LAST_COMMIT" ;;
workspace) printf '  Source:  all Git-tracked files in the current workspace\n' ;;
src) printf '  Source:  Git-tracked files under src/ only\n' ;;
esac
[[ "$py_only" == true ]] && printf '  Filter:  Python files (*.py) only\n'

if [[ -e "$ARCHIVE_PATH" ]]; then
    if [[ "$assume_yes" != true ]]; then
        printf 'Archive exists. Overwrite it? [y/N] '
        read -r answer
        [[ "$answer" =~ ^[Yy]$ ]] || {
            printf 'Archive creation cancelled.\n'
            exit 0
        }
    fi
    rm -f -- "$ARCHIVE_PATH"
fi

list_tracked_files() {
    local path
    while IFS= read -r -d '' path; do
        [[ -e "$PROJECT_ROOT/$path" || -L "$PROJECT_ROOT/$path" ]] || continue
        [[ "$1" != src || "$path" == src/* ]] || continue
        [[ "$py_only" != true || "$path" == *.py ]] || continue
        printf '%s\0' "$path"
    done
}

# set -x
case "$mode" in
commit)
    git -C "$PROJECT_ROOT" archive --format=tar.gz \
        --prefix="${PROJECT_NAME}-${mode}-${LAST_COMMIT}/" \
        HEAD -o "$ARCHIVE_PATH"
    ;;
workspace)
    git -C "$PROJECT_ROOT" ls-files -z | list_tracked_files workspace |
        tar -czf "$ARCHIVE_PATH" -C "$PROJECT_ROOT" --null -T -
    ;;
src)
    git -C "$PROJECT_ROOT" ls-files -z | list_tracked_files src |
        tar -czf "$ARCHIVE_PATH" -C "$PROJECT_ROOT" --null -T -
    ;;
esac
set +x
printf 'Created archive: %s\n' "$ARCHIVE_PATH"
