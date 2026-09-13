#!/usr/bin/bash
# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Promote a release candidate to its final version on the development branch.
#
# Run this on the branch that carries the pre-release version, for example
# 0.5.4rc2 becomes 0.5.4. The script rewrites pyproject.toml, commits the
# change and prints the pull request steps; it never tags anything. Tagging is
# the job of 030_final_release.sh, which runs on the default branch once the
# promotion has been merged.
set -euo pipefail

assume_yes=false
dry_run=false

usage() {
    printf 'Usage: %s [-y|--yes] [-n|--dry-run]\n' "${0##*/}"
    printf '\n'
    printf 'Promotes the pre-release version in pyproject.toml to its final\n'
    printf 'version (0.5.4rc2 -> 0.5.4) and commits the change.\n'
    printf '\n'
    printf 'Options:\n'
    printf '  -y, --yes      Do not ask for confirmation.\n'
    printf '  -n, --dry-run  Print the plan and exit without changing anything.\n'
    printf '  -h, --help     Show this help.\n'
}

while (($#)); do
    case "$1" in
    -y | --yes) assume_yes=true ;;
    -n | --dry-run) dry_run=true ;;
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

if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "The working tree has uncommitted changes; commit or stash them first." >&2
    exit 1
fi

# pyproject.toml is the source of truth for the version.
version="$(uv version --short --dry-run)"
branch="$(git rev-parse --abbrev-ref HEAD)"

if [[ ! "$version" =~ [0-9](a|b|rc|\.dev)[0-9]+$ ]]; then
    if [[ "$version" =~ ^[0-9]+(\.[0-9]+){2,3}$ ]]; then
        printf '%s is already a final version; nothing to promote.\n' "$version" >&2
        printf '\nA candidate is published and promoted first:\n' >&2
        printf '  ./scripts/release/010_pre_release.sh\n' >&2
        printf '  ./scripts/release/020_promote_release.sh\n' >&2
    else
        printf '%s is not a recognised version.\n' "$version" >&2
    fi
    exit 1
fi

# uv computes the stable version: 0.5.4rc2 -> 0.5.4.
final_version="$(uv version --bump stable --dry-run --short)"
[[ "$final_version" =~ ^[0-9]+(\.[0-9]+){2,3}$ ]] || {
    printf 'Could not derive a final version from %s (got %s).\n' "$version" "$final_version" >&2
    exit 1
}

default_branch="$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null | sed 's|^origin/||')"
default_branch="${default_branch:-main}"
on_default_branch=false
if [[ "$branch" == "$default_branch" ]]; then
    on_default_branch=true
fi

commit_message="chore: release $final_version"

printf '\nRelease promotion plan\n'
printf '  Project:      %s\n' "$project_root"
printf '  Branch:       %s\n' "$branch"
printf '  Version:      %s -> %s\n' "$version" "$final_version"
printf '  Commit:       %s\n' "$commit_message"
if [[ "$on_default_branch" == true ]]; then
    printf '  Note:         this is the default branch; promotion normally runs on a\n'
    printf '                development branch and merges into %s.\n' "$default_branch"
fi

if [[ "$dry_run" == true ]]; then
    printf '\nDry run: nothing was changed.\n'
    exit 0
fi

if [[ "$assume_yes" != true ]]; then
    printf '\nApply the promotion and commit it now? [y/N] '
    read -r answer
    [[ "$answer" =~ ^[Yy]$ ]] || {
        printf 'Promotion cancelled.\n'
        exit 0
    }
fi

set -x
uv version "$final_version" --no-sync
git add pyproject.toml
git commit -m "$commit_message"
set +x

printf '\nPromoted %s to %s on %s.\n' "$version" "$final_version" "$branch"
printf '\nNext steps:\n'
if [[ "$on_default_branch" == false ]]; then
    printf '  1. push the branch and open a pull request against %s:\n' "$default_branch"
    printf '       git push origin %s\n' "$branch"
    printf '       gh pr create --base %s --title "Release %s" --body "..."\n' \
        "$default_branch" "$final_version"
    printf '       gh pr merge --squash\n'
    printf '  2. from the %s worktree, delete the development branch\n' "$default_branch"
    printf '     and tag the merged version:\n'
    printf '       ./scripts/release/030_final_release.sh\n'
else
    printf '  1. push the promoted commit:\n'
    printf '       git push origin %s\n' "$branch"
    printf '  2. once CI is green, tag the release:\n'
    printf '       ./scripts/release/030_final_release.sh\n'
fi
