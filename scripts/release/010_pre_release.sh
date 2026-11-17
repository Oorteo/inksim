#!/usr/bin/bash
# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Publish a pre-release build for testing, without touching pyproject.toml.
#
# The version in pyproject.toml is the version the branch is heading towards;
# it is never rewritten for a release. This script reads it, appends the next
# release-candidate counter and creates a tag on the current commit. The
# release workflow derives the exact distribution version from that tag, so no
# commit is added and no reviewer has to approve a version-only change.
set -euo pipefail

push=true
dry_run=false
assume_yes=false
fetch=true

usage() {
    printf 'Usage: %s [-y|--yes] [-n|--dry-run] [--no-push] [--no-fetch]\n' "${0##*/}"
    printf '\n'
    printf 'Creates the next pre-release tag for the current commit.\n'
    printf '  Version:    from pyproject.toml (unchanged)\n'
    printf '  Tag:        next v<version>-rc.N\n'
    printf '  Push:       starts GitHub Actions "Release wheel"\n'
    printf '  On success: test wheel + source archive attached to GitHub pre-release\n'
    printf '  PyPI:       never\n'
    printf '  --no-push:  local tag only; push it to start the workflow\n'
    printf '\n'
    printf 'When HEAD differs from its upstream, fetch and push are disabled automatically.\n'
    printf 'The local tag list may differ from origin in that mode.\n'
    printf 'With uncommitted changes, you can create a local tag for HEAD; those changes are excluded.\n'
    printf '\n'
    printf 'Options:\n'
    printf '  -y, --yes      Do not ask for confirmation.\n'
    printf '  -n, --dry-run  Print the plan and exit without changing anything.\n'
    printf '      --no-push  Create the tag locally, but do not push it.\n'
    printf '      --no-fetch Use the existing remote refs without fetching.\n'
    printf '  -h, --help     Show this help.\n'
}

while (($#)); do
    case "$1" in
    -y | --yes) assume_yes=true ;;
    -n | --dry-run) dry_run=true ;;
    --no-push) push=false ;;
    --no-fetch) fetch=false ;;
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

branch="$(git rev-parse --abbrev-ref HEAD)"
commit="$(git rev-parse HEAD)"
working_tree_changes="$(git status --porcelain --untracked-files=normal)"
dirty_worktree=false
if [[ -n "$working_tree_changes" ]]; then
    dirty_worktree=true
fi

upstream=""
if [[ "$branch" != "HEAD" ]]; then
    upstream="$(git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null || true)"
fi

local_only=false
upstream_commit=""
if [[ -n "$upstream" ]]; then
    upstream_commit="$(git rev-parse --verify -q "${upstream}^{commit}" || true)"
fi
if [[ -z "$upstream_commit" || "$upstream_commit" != "$commit" ]]; then
    local_only=true
fi
if [[ "$dirty_worktree" == true ]]; then
    local_only=true
fi
if [[ "$local_only" == true ]]; then
    fetch=false
    push=false
    if [[ -z "$upstream_commit" || "$upstream_commit" != "$commit" ]]; then
        echo "HEAD is not synchronized with its upstream; disabling fetch and push." >&2
    fi
    echo "Using local tags only; the next RC number may differ from origin." >&2
    echo "Any tag created will remain local." >&2
fi
if [[ "$dirty_worktree" == true ]]; then
    echo "The working tree has uncommitted changes; disabling fetch and push." >&2
    echo "A local tag will point to HEAD; uncommitted and untracked changes are excluded." >&2
fi

if [[ "$fetch" == true ]]; then
    if ! git fetch --quiet --tags origin; then
        echo "Could not fetch tags from origin; continuing with the local ones." >&2
    fi
fi

mapfile -t current_release_tags < <(git tag --points-at "$commit" --list 'v*')
if ((${#current_release_tags[@]})); then
    printf 'Commit %s already has release tag(s): %s\n' \
        "${commit:0:12}" "${current_release_tags[*]}" >&2
    echo "Each commit may have only one v* release tag." >&2
    echo "Create a new commit before creating another release candidate." >&2
    exit 1
fi

# pyproject.toml holds the version the branch is heading towards. It is only
# read here, never rewritten.
target_version="$(uv version --short --dry-run)"

# Work on the release version itself: 0.5.4rc2 or 0.5.4 both start from 0.5.4.
base_version="$(printf '%s' "$target_version" | sed -E 's/(a|b|rc|\.dev)[0-9]+$//')"
[[ "$base_version" =~ ^[0-9]+(\.[0-9]+){2,3}$ ]] || {
    printf '%s in pyproject.toml is not a plain release version.\n' "$target_version" >&2
    exit 1
}

# The candidate counter comes from the tags that already exist for this
# version. A new candidate must tag a new commit.
last_candidate=0
while IFS= read -r existing; do
    [[ "$existing" =~ ^v${base_version}-rc\.([0-9]+)$ ]] || continue
    ((BASH_REMATCH[1] > last_candidate)) && last_candidate="${BASH_REMATCH[1]}"
done < <(git tag --list "v${base_version}-rc.*")
next_candidate=$((last_candidate + 1))

tag="v${base_version}-rc.${next_candidate}"
# PEP 440 spells the candidate 0.5.4rc1; the tag spells it v0.5.4-rc.1.
dist_version="${base_version}rc${next_candidate}"

printf '\nPre-release plan for: %s\n' "$project_root"
printf '  Branch:       %s\n' "$branch"
printf '  Commit:       %s %s\n' "${commit:0:12}" "$(git log -1 --pretty=%s)"
printf '  Version:      %s (from pyproject.toml, unchanged)\n' "$target_version"
printf '  Tag:          %s (pre-release)\n' "$tag"
printf '  Builds:       inksim-%s\n' "$dist_version"
printf '  Commit made:  none\n'
printf '  Push:         %s\n' "$(if [[ "$push" == true ]]; then echo "tag only"; else echo "no"; fi)"
printf '  Latest:       unchanged, pre-releases never become latest\n'

if [[ "$dry_run" == true ]]; then
    printf '\nDry run: nothing was changed.\n'
    exit 0
fi

if [[ "$assume_yes" != true ]]; then
    printf '\nCreate and %s %s now? [y/N] ' \
        "$(if [[ "$push" == true ]]; then echo "push"; else echo "keep"; fi)" "$tag"
    read -r answer
    [[ "$answer" =~ ^[Yy]$ ]] || {
        printf 'Pre-release cancelled.\n'
        exit 0
    }
fi

set -x
git tag -a "$tag" -m "$tag"
if [[ "$push" == true ]]; then
    git push origin "$tag"
fi
set +x

if [[ "$push" == true ]]; then
    printf '\nTag %s pushed; install the test wheel after Actions succeeds:\n' "$tag"
    printf '  pip install https://github.com/<owner>/<repo>/releases/download/%s/inksim-%s-py3-none-any.whl\n' \
        "$tag" "$dist_version"
else
    printf '\nLocal tag only; push to start the test build:\n  git push origin %s\n' "$tag"
fi
printf '\nWhen the candidate is accepted, merge the work and tag the release:\n'
printf '  ./scripts/release/020_final_release.sh\n'
