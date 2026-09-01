#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Install the locally built wheel as an isolated uv tool; no PyPI upload occurs.
# Runs on macOS, Linux, or Windows via Bash (Git Bash/WSL).

# We want to execute: uv tool install ....

set -euo pipefail

assume_yes=false
case "${1:-}" in
"") ;;
-y | --yes) assume_yes=true ;;
-h | --help)
    printf 'Usage: %s [-y|--yes]\n' "$0"
    exit 0
    ;;
*)
    printf 'Usage: %s [-y|--yes]\n' "$0" >&2
    exit 1
    ;;
esac

source_path="${BASH_SOURCE[0]}"
# Resolve symlinks portably; this is the Bash equivalent of readlink -f.
while [[ -L "$source_path" ]]; do
    script_dir="$(cd -P "$(dirname "$source_path")" && pwd)"
    source_path="$(readlink "$source_path")"
    [[ "$source_path" = /* ]] || source_path="$script_dir/$source_path"
done
script_dir="$(cd -P "$(dirname "$source_path")" && pwd)"
# Find the project root instead of assuming this script is one level below it.
project_root="$script_dir"
while [[ ! -f "$project_root/pyproject.toml" && "$project_root" != "/" ]]; do
    project_root="$(cd -- "$project_root/.." && pwd)"
done
[[ -f "$project_root/pyproject.toml" ]] || {
    echo "Could not find pyproject.toml above $script_dir." >&2
    exit 1
}
python_version="${PYTHON_VERSION:-3.14}"

shopt -s nullglob
wheels=("$project_root"/dist/inksim-*.whl)
if ((${#wheels[@]} != 1)); then
    echo "Expected exactly one wheel in $project_root/dist; run scripts/pypi/010_build.sh first." >&2
    exit 1
fi

install_options=(--force --reinstall --python "$python_version")

printf 'Installing local wheel: %s\n' "${wheels[0]}"

if [[ "$assume_yes" != true ]]; then
    printf 'Continue with uv tool install? [y/N] '
    read -r answer
    [[ "$answer" =~ ^[Yy]$ ]] || {
        printf 'Installation cancelled.\n'
        exit 0
    }
fi

set -x
exec uv tool install "${install_options[@]}" "${wheels[0]}"
