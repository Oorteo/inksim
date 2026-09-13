#!/usr/bin/bash
# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Publish a final release by tagging the current tip of the main branch.
#
# The version is read from the release branch, not from the working tree, so
# the tag always matches the distributions the release workflow builds. The
# script refuses to tag a pre-release version and refuses to reuse an existing
# tag, keeping the version in pyproject.toml and the tag name in sync.
set -euo pipefail

branch="${RELEASE_BRANCH:-}"
push=true
dry_run=false
assume_yes=false
require_green=false
fetch=true

usage() {
    printf 'Usage: %s [-y|--yes] [-n|--dry-run] [--branch <name>]\n' "${0##*/}"
    printf '          [--no-push] [--no-fetch] [--require-green]\n'
    printf '\n'
    printf 'Tags the tip of the release branch with the version from its\n'
    printf 'pyproject.toml and pushes the tag, which publishes a final release.\n'
    printf '\n'
    printf 'Options:\n'
    printf '  -y, --yes        Do not ask for confirmation.\n'
    printf '  -n, --dry-run    Print the plan and exit without changing anything.\n'
    printf '      --branch     Release branch to tag (default: the default branch).\n'
    printf '      --no-push    Create the tag locally, but do not push it.\n'
    printf '      --no-fetch   Use the existing remote refs without fetching.\n'
    printf '      --require-green\n'
    printf '                   Fail unless every CI check run passed.\n'
    printf '  -h, --help       Show this help.\n'
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
    --require-green) require_green=true ;;
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

if [[ -z "$branch" ]]; then
    branch="$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null | sed 's|^origin/||')"
    branch="${branch:-main}"
fi

remote_ref="origin/$branch"
git rev-parse -q --verify "refs/remotes/$remote_ref" >/dev/null || {
    echo "No remote branch $remote_ref; fetch first or pass --branch." >&2
    exit 1
}

# Read the version from the branch that will be tagged, not from the working
# tree: the release workflow builds whatever the tag points at.
version="$(git show "$remote_ref:pyproject.toml" | sed -n 's/^version = "\(.*\)"$/\1/p' | head -1)"
[[ -n "$version" ]] || {
    echo "Could not read the version from $remote_ref:pyproject.toml." >&2
    exit 1
}

if [[ ! "$version" =~ ^[0-9]+(\.[0-9]+){2,3}$ ]]; then
    if [[ "$version" =~ [0-9](a|b|rc|\.dev)[0-9]+$ ]]; then
        printf '%s is still a pre-release; promote it first:\n' "$version" >&2
        printf '  uv version --bump stable\n' >&2
        printf '  git add pyproject.toml && git commit -m "chore: release <version>"\n' >&2
        printf '  open a pull request against %s and merge it\n' "$branch" >&2
    else
        printf '%s is not a plain release version.\n' "$version" >&2
    fi
    exit 1
fi

sha="$(git rev-parse "$remote_ref")"
tag="v$version"

git rev-parse -q --verify "refs/tags/$tag" >/dev/null && {
    printf '%s already has the tag %s, so there is nothing to release.\n' "$remote_ref" "$tag" >&2
    printf '\nTo release a new version, promote the project version first:\n' >&2
    printf '  git switch <release branch>\n' >&2
    printf '  uv version %s --bump patch\n' "${version##*/}" >&2
    printf '  git add pyproject.toml && git commit -m "chore: release <new version>"\n' >&2
    printf '  open a pull request against %s and merge it\n' "$branch" >&2
    exit 1
}
git ls-remote --exit-code --tags origin "refs/tags/$tag" >/dev/null 2>&1 && {
    printf 'Tag %s already exists on origin, so %s was released already.\n' "$tag" "$version" >&2
    exit 1
}

# The working tree is usually a feature branch, so a difference here is
# expected; it only hints at a forgotten promotion.
working_version="$(sed -n 's/^version = "\(.*\)"$/\1/p' pyproject.toml | head -1)"

printf '\nFinal release plan\n'
printf '  Project:      %s\n' "$project_root"
printf '  Branch:       %s (%s)\n' "$branch" "$remote_ref"
printf '  Commit:       %s\n' "${sha:0:12}"
printf '  Version:      %s\n' "$version"
printf '  Tag:          %s (published release, becomes latest)\n' "$tag"
if [[ -n "$working_version" && "$working_version" != "$version" ]]; then
    printf '  Note:         the working tree still says %s\n' "$working_version"
fi

# Report CI status for the commit that is about to be tagged.
if command -v gh >/dev/null 2>&1; then
    repository="$(gh repo view --json nameWithOwner --jq .nameWithOwner 2>/dev/null || true)"
    if [[ -n "$repository" ]]; then
        checks="$(gh api "repos/$repository/commits/$sha/check-runs?per_page=100" \
            --jq '[.check_runs[] | "\(.status)/\(.conclusion // "running")"] | .[]' 2>/dev/null || true)"
        if [[ -z "$checks" ]]; then
            printf '  CI checks:    none reported\n'
        else
            total="$(printf '%s\n' "$checks" | wc -l | tr -d ' ')"
            green="$(printf '%s\n' "$checks" | grep -c '^completed/success$' || true)"
            printf '  CI checks:    %s of %s passed\n' "$green" "$total"
            if [[ "$green" != "$total" ]] && [[ "$require_green" == true ]]; then
                printf '\nNot every check passed and --require-green was given.\n' >&2
                printf '%s\n' "$checks" | sed 's/^/    /' >&2
                exit 1
            fi
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
