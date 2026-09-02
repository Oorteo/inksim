#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Run the project's test suite from any working directory.
set -euo pipefail

usage() {
    printf 'Usage: %s [-y|--yes] [pytest options]\n' "$0"
    printf '  -y, --yes  Run tests without confirmation.\n'
    printf '  -h, --help Show this help and exit.\n'
}

ASSUME_YES=false
PYTEST_ARGS=()
for argument in "$@"; do
    case "$argument" in
    -y | --yes) ASSUME_YES=true ;;
    -h | --help)
        usage
        exit 0
        ;;
    *) PYTEST_ARGS+=("$argument") ;;
    esac
done

SOURCE="${BASH_SOURCE[0]}"
while [[ -L "$SOURCE" ]]; do
    SCRIPT_DIR="$(cd -P "$(dirname "$SOURCE")" >/dev/null 2>&1 && pwd)"
    SOURCE="$(readlink "$SOURCE")"
    [[ "$SOURCE" = /* ]] || SOURCE="$SCRIPT_DIR/$SOURCE"
done
SCRIPT_DIR="$(cd -P "$(dirname "$SOURCE")" >/dev/null 2>&1 && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." >/dev/null 2>&1 && pwd)"

cd "$PROJECT_ROOT"
if [[ "$ASSUME_YES" != true ]]; then
    printf 'Run the InkSim test suite now? [y/N] '
    read -r answer
    [[ "$answer" =~ ^[Yy]([Ee][Ss])?$ ]] || {
        printf 'Test run cancelled.\n'
        exit 0
    }
fi

LOG_PATH="log/tests/latest.log"
mkdir -p "$(dirname "$LOG_PATH")"

set +e
{
    printf 'InkSim test run: %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')"
    printf 'Command: uv run pytest tests -vv --durations=10'
    if ((${#PYTEST_ARGS[@]} > 0)); then
        printf ' %q' "${PYTEST_ARGS[@]}"
    fi
    printf '\n\n'
    uv run pytest tests -vv --durations=10 "${PYTEST_ARGS[@]}"
} 2>&1 | tee "$LOG_PATH"
test_status="${PIPESTATUS[0]}"
set -e
exit "$test_status"
