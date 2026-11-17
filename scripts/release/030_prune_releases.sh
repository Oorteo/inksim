#!/usr/bin/bash
# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Prune old GitHub pre-releases so that experimental builds do not pile up.
#
# GitHub expires Actions artifacts and caches automatically, but releases and
# their Git tags stay forever until they are deleted. This script lists the
# pre-releases, keeps the newest ones and deletes the rest together with their
# tags. Published (non pre-release) releases are never touched.
set -euo pipefail

keep=5

usage() {
    printf 'Usage: %s [-y|--yes] [-n|--dry-run] [--keep <count>]\n' "${0##*/}"
    printf '\n'
    printf 'Deletes GitHub pre-releases except the newest <count> ones.\n'
    printf '\n'
    printf 'Options:\n'
    printf '  -y, --yes        Do not ask for confirmation.\n'
    printf '  -n, --dry-run    List what would be deleted and exit.\n'
    printf '  --keep <count>   Number of pre-releases to keep (default: %s).\n' "$keep"
    printf '  -h, --help       Show this help.\n'
}

assume_yes=false
dry_run=false
while (($#)); do
    case "$1" in
    -y | --yes) assume_yes=true ;;
    -n | --dry-run) dry_run=true ;;
    --keep)
        shift
        [[ "${1:-}" =~ ^[0-9]+$ ]] || {
            printf '%s\n' 'The --keep option expects a non-negative number.' >&2
            exit 1
        }
        keep="$1"
        ;;
    -h | --help)
        usage
        exit 0
        ;;
    *)
        printf 'Unknown argument: %s\n\n' "$1" >&2
        usage >&2
        exit 1
        ;;
    esac
    shift
done

command -v gh >/dev/null 2>&1 || {
    echo "The GitHub CLI (gh) is required to manage releases." >&2
    exit 1
}

source_path="${BASH_SOURCE[0]}"
# Resolve symlinks portably; this is the Bash equivalent of readlink -f.
while [[ -L "$source_path" ]]; do
    script_dir="$(cd -P "$(dirname "$source_path")" && pwd)"
    source_path="$(readlink "$source_path")"
    [[ "$source_path" = /* ]] || source_path="$script_dir/$source_path"
done
script_dir="$(cd -P "$(dirname "$source_path")" && pwd)"
# Find the project root instead of assuming the script depth.
project_root="$script_dir"
while [[ ! -f "$project_root/pyproject.toml" && "$project_root" != "/" ]]; do
    project_root="$(cd -- "$project_root/.." && pwd)"
done
[[ -f "$project_root/pyproject.toml" ]] || {
    echo "Could not find pyproject.toml above $script_dir." >&2
    exit 1
}
cd "$project_root"

git rev-parse --git-dir >/dev/null 2>&1 || {
    echo "$project_root is not a Git repository." >&2
    exit 1
}

# Newest first; the releases API returns them in publication order. Paginate so
# that repositories with more releases than one page are still pruned fully.
mapfile -t prerelease_tags < <(
    gh api --paginate 'repos/{owner}/{repo}/releases?per_page=100' \
        --jq '.[] | select(.prerelease) | .tag_name'
)
total="${#prerelease_tags[@]}"
if ((keep > total)); then
    keep="$total"
fi
to_delete=("${prerelease_tags[@]:keep}")

printf '\nPre-release pruning for: %s\n' "$project_root"
printf '  Pre-releases found: %s\n' "$total"
printf '  Keeping the newest: %s\n' "$keep"
if ((${#to_delete[@]} == 0)); then
    printf '\nNothing to delete.\n'
    exit 0
fi

printf '  Deleting:           %s\n' "${#to_delete[@]}"
for tag in "${to_delete[@]}"; do
    printf '    %s\n' "$tag"
done

if [[ "$dry_run" == true ]]; then
    printf '\nDry run: nothing was deleted.\n'
    exit 0
fi

if [[ "$assume_yes" != true ]]; then
    printf '\nDelete these pre-releases and their tags? [y/N] '
    read -r answer
    [[ "$answer" =~ ^[Yy]$ ]] || {
        printf 'Pruning cancelled.\n'
        exit 0
    }
fi

for tag in "${to_delete[@]}"; do
    printf 'Deleting %s\n' "$tag"
    gh release delete "$tag" --cleanup-tag --yes
done
