#!/usr/bin/bash
# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Tag a final release from the default branch, after the promotion merge.
#
# Run this from the worktree that holds the default branch, once
# 020_promote_release.sh has been merged and the development branch deleted.
# pyproject.toml is the source of truth for the version; the script tags the
# current commit of the checked-out branch, so the tag name, the version in
# the metadata and the distributions built by the release workflow all agree.
set -euo pipefail

push=true
dry_run=false
assume_yes=false
require_green=true
fetch=true

usage() {
    printf 'Usage: %s [-y|--yes] [-n|--dry-run]\n' "${0##*/}"
    printf '          [--branch <name>] [--no-push] [--no-fetch] [--no-require-green]\n'
    printf '\n'
    printf 'Tags the current commit with the final version from pyproject.toml and\n'
    printf 'pushes the tag, which publishes the release and its distributions.\n'
    printf '\n'
    printf 'Options:\n'
    printf '  -y, --yes             Do not ask for confirmation.\n'
    printf '  -n, --dry-run         Print the plan and exit without changing anything.\n'
    printf '      --branch <name>   Branch to tag (default: the checked-out branch).\n'
    printf '      --no-push         Create the tag locally, but do not push it.\n'
    printf '      --no-fetch        Use the existing remote refs without fetching.\n'
    printf '      --no-require-green\n'
    printf '                        Tag even when a CI check did not pass.\n'
    printf '  -h, --help            Show this help.\n'
}

while (($#)); do
    case "$1" in
    -y | --yes) assume_yes=true ;;
    -n | --dry-run) dry_run=true ;;
    --branch)
        shift
        [[ -n "${1:-}" ]] || {
            printf '%s\n' 'The --branch option expects a branch name.' >&2
            exit 1
        }
        branch="$1"
        ;;
    --no-push) push=false ;;
    --no-fetch) fetch=false ;;
    --no-require-green) require_green=false ;;
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

if [[ "$fetch" == true ]]; then
    if ! git fetch --quiet origin; then
        echo "Could not fetch from origin; continuing with the existing refs." >&2
    fi
fi

current_branch="$(git rev-parse --abbrev-ref HEAD)"
if [[ -z "${branch:-}" ]]; then
    branch="$current_branch"
fi
if [[ "$branch" == "HEAD" ]]; then
    echo "The repository is in a detached HEAD state; switch to a branch first." >&2
    exit 1
fi

default_branch="$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null | sed 's|^origin/||')"
default_branch="${default_branch:-main}"

# pyproject.toml is the source of truth for the version.
version="$(uv version --short --dry-run)"
[[ -n "$version" ]] || {
    echo "Could not read the version from pyproject.toml." >&2
    exit 1
}

if [[ ! "$version" =~ ^[0-9]+(\.[0-9]+){2,3}$ ]]; then
    if [[ "$version" =~ [0-9](a|b|rc|\.dev)[0-9]+$ ]]; then
        printf '%s is still a pre-release; promote it first:\n' "$version" >&2
        printf '  ./scripts/release/020_promote_release.sh\n' >&2
        printf '  git push origin %s\n' "$branch" >&2
        printf '  gh pr create --base %s --title "Release <version>"\n' "$default_branch" >&2
        printf '  gh pr merge --squash\n' >&2
        printf 'then run this script again from the %s worktree.\n' "$default_branch" >&2
    else
        printf '%s is not a plain release version.\n' "$version" >&2
    fi
    exit 1
fi

if [[ "$branch" == "$current_branch" ]]; then
    sha="$(git rev-parse HEAD)"
else
    sha="$(git rev-parse "$branch")"
fi
tag="v$version"

git rev-parse -q --verify "refs/tags/$tag" >/dev/null && {
    printf 'The tag %s already exists locally, so %s was released already.\n' "$tag" "$version" >&2
    printf '\nTo release a new version, promote the project version first:\n' >&2
    printf '  git switch <development branch>\n' >&2
    printf '  uv version %s --bump patch\n' "$version" >&2
    printf '  git add pyproject.toml && git commit -m "chore: release <new version>"\n' >&2
    exit 1
}
git ls-remote --exit-code --tags origin "refs/tags/$tag" >/dev/null 2>&1 && {
    printf 'The tag %s already exists on origin, so %s was released already.\n' "$tag" "$version" >&2
    exit 1
}

printf '\nFinal release plan\n'
printf '  Project:      %s\n' "$project_root"
printf '  Branch:       %s%s\n' "$branch" \
    "$(if [[ "$branch" == "$current_branch" ]]; then echo " (checked out)"; else echo ""; fi)"
printf '  Commit:       %s\n' "${sha:0:12}"
printf '  Version:      %s (from pyproject.toml)\n' "$version"
printf '  Tag:          %s (published release, becomes latest)\n' "$tag"
if [[ "$branch" != "$default_branch" ]]; then
    printf '  Note:         %s is not the default branch (%s); the tag will point at\n' "$branch" "$default_branch"
    printf '                a commit that is not on %s.\n' "$default_branch"
fi

# Report the CI status of the commit that is about to be tagged.
repository=""
if command -v gh >/dev/null 2>&1; then
    repository="$(gh repo view --json nameWithOwner --jq .nameWithOwner 2>/dev/null || true)"
fi
checks=""
if [[ -n "$repository" ]]; then
    checks="$(gh api "repos/$repository/commits/$sha/check-runs?per_page=100" \
        --jq '[.check_runs[] | "\(.name): \(.status)/\(.conclusion // "running")"] | .[]' 2>/dev/null || true)"
fi

if [[ -z "$checks" ]]; then
    if [[ "$require_green" == true ]]; then
        printf '  CI checks:    none reported for %s\n' "${sha:0:12}"
        printf '\nNo check runs were found for this commit, so the green requirement cannot be satisfied.\n' >&2
        printf 'Wait for CI to report, or pass --no-require-green to tag anyway.\n' >&2
        exit 1
    fi
    printf '  CI checks:    none reported\n'
else
    total="$(printf '%s\n' "$checks" | wc -l | tr -d ' ')"
    green="$(printf '%s\n' "$checks" | grep -c ': completed/success$' || true)"
    printf '  CI checks:    %s of %s passed\n' "$green" "$total"
    if [[ "$green" != "$total" ]]; then
        printf '%s\n' "$checks" | sed 's/^/                /'
        if [[ "$require_green" == true ]]; then
            printf '\nNot every check passed.\n' >&2
            printf 'Fix the failures, or pass --no-require-green to tag anyway.\n' >&2
            exit 1
        fi
    fi
fi

if [[ "$dry_run" == true ]]; then
    printf '\nDry run: nothing was changed.\n'
    exit 0
fi

if [[ "$assume_yes" != true ]]; then
    printf '\nCreate and %s %s now? [y/N] ' "$(if [[ "$push" == true ]]; then echo "push"; else echo "keep"; fi)" "$tag"
    read -r answer
    [[ "$answer" =~ ^[Yy]$ ]] || {
        printf 'Final release cancelled.\n'
        exit 0
    }
fi

set -x
git tag -a "$tag" "$sha" -m "$tag"
if [[ "$push" == true ]]; then
    git push origin "$tag"
fi
set +x

printf '\n'
if [[ "$push" == true ]]; then
    printf 'Tag %s pushed. The release workflow is building the distributions now:\n' "$tag"
    printf '  https://github.com/%s/actions\n' "${repository:-Oorteo/inksim}"
    printf '  https://github.com/%s/releases/tag/%s\n' "${repository:-Oorteo/inksim}" "$tag"
    printf '\nAfter the release looks good, publish to PyPI with:\n'
    printf '  ./scripts/pypi/010_build.sh && ./scripts/pypi/030_send_pypi.sh\n'
else
    printf 'Tag %s created locally. Push it with:\n' "$tag"
    printf '  git push origin %s\n' "$tag"
fi
