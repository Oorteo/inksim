#!/usr/bin/bash
# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Publish a pre-release build for testing.
#
# The script bumps the project version to the next release candidate (for
# example 0.5.3 -> 0.5.4rc1, then 0.5.4rc1 -> 0.5.4rc2), commits the change,
# creates an annotated tag and pushes both. The tag name spells the pre-release
# with a hyphen (v0.5.4-rc.1) so that the release workflow can tell it apart
# from a stable tag and publish it as a GitHub pre-release.
set -euo pipefail

usage() {
    printf 'Usage: %s [-y|--yes] [-n|--dry-run] [--no-push]\n' "${0##*/}"
    printf '\n'
    printf 'Bumps the project version to the next release candidate, commits it,\n'
    printf 'creates an annotated tag and pushes commit and tag.\n'
    printf '\n'
    printf 'Options:\n'
    printf '  -y, --yes      Do not ask for confirmation.\n'
    printf '  -n, --dry-run  Print the plan and exit without changing anything.\n'
    printf '      --no-push  Commit and tag locally, but do not push.\n'
    printf '  -h, --help     Show this help.\n'
}

assume_yes=false
dry_run=false
push=true
while (($#)); do
    case "$1" in
    -y | --yes) assume_yes=true ;;
    -n | --dry-run) dry_run=true ;;
    --no-push) push=false ;;
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

# The version is read with --dry-run and written with --no-sync so that uv
# neither re-locks nor syncs the environment during a release.
current_version="$(uv version --short --dry-run)"
branch="$(git rev-parse --abbrev-ref HEAD)"

# A release candidate in progress increments its own counter, anything else
# starts a candidate for the next patch version.
if [[ "$current_version" =~ [0-9](a|b|rc|\.dev)[0-9]+$ ]]; then
    next_version="$(uv version --bump rc --dry-run --short)"
else
    next_version="$(uv version --bump patch --bump rc --dry-run --short)"
fi

# PEP 440 writes the candidate as 0.5.4rc1, the tag uses 0.5.4-rc.1.
tag_version="$(printf '%s' "$next_version" | sed -E 's/^(.*[0-9])(a|b|rc|\.dev)([0-9]+)$/\1-\2.\3/')"
[[ "$tag_version" != "$next_version" ]] || {
    echo "Refusing to tag: '$next_version' is not a pre-release version." >&2
    exit 1
}
tag="v$tag_version"

if git rev-parse -q --verify "refs/tags/$tag" >/dev/null; then
    echo "Tag $tag already exists." >&2
    exit 1
fi

printf '\nPre-release plan for: %s\n' "$project_root"
printf '  Branch:       %s\n' "$branch"
printf '  Version:      %s -> %s\n' "$current_version" "$next_version"
printf '  Tag:          %s (pre-release)\n' "$tag"
printf '  Commit:       chore: release %s\n' "$next_version"
printf '  Push:         %s\n' "$(if [[ "$push" == true ]]; then echo "yes (branch and tag)"; else echo "no"; fi)"
printf '  Distributes:  %s %s via the release workflow\n' "inksim" "$next_version"
printf '  Latest:       unchanged, pre-releases never become "latest"\n'

if [[ "$dry_run" == true ]]; then
    printf '\nDry run: nothing was changed.\n'
    exit 0
fi

if [[ "$assume_yes" != true ]]; then
    printf '\nCreate the commit and the tag now? [y/N] '
    read -r answer
    [[ "$answer" =~ ^[Yy]$ ]] || {
        printf 'Pre-release cancelled.\n'
        exit 0
    }
fi

set -x
uv version "$next_version" --no-sync
git add pyproject.toml
git commit -m "chore: release $next_version"
git tag -a "$tag" -m "$tag"
if [[ "$push" == true ]]; then
    git push origin HEAD
    git push origin "$tag"
fi
set +x

printf '\nPre-release %s is building. Testers install it with:\n' "$tag"
printf '  pip install https://github.com/<owner>/<repo>/releases/download/%s/inksim-%s-py3-none-any.whl\n' \
    "$tag" "$next_version"
printf '\nWhen the candidate is accepted, promote it to a final version:\n'
printf '  ./scripts/release/020_promote_release.sh\n'
