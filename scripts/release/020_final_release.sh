#!/usr/bin/bash
# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Tag a final release from the default branch.
#
# Once the work for the release has been merged, the script targets the origin
# default branch unless --branch explicitly selects another branch. The version
# in pyproject.toml names the release and is never rewritten.
set -euo pipefail

push=true
dry_run=false
assume_yes=false
require_green=true
fetch=true
branch_explicit=false

usage() {
    printf 'Usage: %s [-y|--yes] [-n|--dry-run]\n' "${0##*/}"
    printf '          [--branch <name>] [--no-push] [--no-fetch] [--no-require-green]\n'
    printf '\n'
    printf 'Tags the selected branch commit with the final version from pyproject.toml and\n'
    printf 'pushes the tag, which publishes the release and its distributions.\n'
    printf 'The default target is the origin default branch; --branch explicitly selects another.\n'
    printf 'A local-only target or dirty worktree disables fetch and push automatically.\n'
    printf 'In local-only mode, remote tags and CI status are not checked.\n'
    printf '\n'
    printf 'Options:\n'
    printf '  -y, --yes             Do not ask for confirmation.\n'
    printf '  -n, --dry-run         Print the plan and exit without changing anything.\n'
    printf '      --branch <name>   Explicitly select a branch other than the default branch.\n'
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
        branch_explicit=true
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

current_branch="$(git rev-parse --abbrev-ref HEAD)"
default_branch="$(
    git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null |
        sed 's|^origin/||' || true
)"
default_branch="${default_branch:-main}"
if [[ -z "${branch:-}" ]]; then
    branch="$default_branch"
fi

resolve_target_commit() {
    if [[ "$branch" == "$current_branch" ]]; then
        git rev-parse HEAD
    elif [[ "$branch" == "$default_branch" ]] && \
        git show-ref --verify --quiet "refs/remotes/origin/$branch"; then
        git rev-parse "refs/remotes/origin/$branch"
    elif git show-ref --verify --quiet "refs/heads/$branch"; then
        git rev-parse "refs/heads/$branch"
    elif git show-ref --verify --quiet "refs/remotes/origin/$branch"; then
        git rev-parse "refs/remotes/origin/$branch"
    else
        printf 'Branch %s was not found locally or on origin.\n' "$branch" >&2
        return 1
    fi
}

# Detect local-only targets before fetching so a fetch cannot make a local
# commit appear synchronized. Remote refs may be stale, so this is conservative.
sha="$(resolve_target_commit)"
remote_branches_containing_target="$(
    git for-each-ref --contains="$sha" --format='%(refname)' refs/remotes/origin
)"
working_tree_changes="$(git status --porcelain --untracked-files=normal)"
local_only=false
if [[ -z "$remote_branches_containing_target" || -n "$working_tree_changes" ]]; then
    local_only=true
    fetch=false
    push=false
    if [[ -z "$remote_branches_containing_target" ]]; then
        echo "The selected commit is not in the local origin tracking refs; disabling fetch and push." >&2
    fi
    if [[ -n "$working_tree_changes" ]]; then
        echo "The working tree has uncommitted changes; disabling fetch and push." >&2
    fi
    echo "Using local tags only; the remote tag list and CI status are not checked." >&2
    echo "Any tag created will remain local; uncommitted changes are excluded." >&2
fi

if [[ "$branch_explicit" != true && "$local_only" != true && \
    "$branch" == "$default_branch" ]] && \
    git show-ref --verify --quiet "refs/remotes/origin/$branch"; then
    sha="$(git rev-parse "refs/remotes/origin/$branch")"
fi

if [[ "$fetch" == true ]]; then
    if ! git fetch --quiet origin; then
        echo "Could not fetch from origin; continuing with the existing refs." >&2
    fi
    if [[ "$branch_explicit" != true && "$local_only" != true && \
        "$branch" == "$default_branch" ]] && \
        git show-ref --verify --quiet "refs/remotes/origin/$branch"; then
        sha="$(git rev-parse "refs/remotes/origin/$branch")"
    else
        sha="$(resolve_target_commit)"
    fi
fi

# Read the release version from the selected commit, not the current worktree.
version="$(
    git show "$sha:pyproject.toml" |
        uv run --project "$project_root" --no-sync python -c \
            'import sys, tomllib; print(tomllib.load(sys.stdin.buffer)["project"]["version"])'
)"
[[ -n "$version" ]] || {
    echo "Could not read the version from pyproject.toml." >&2
    exit 1
}

# A pre-release in the file means the branch is still a staging branch; only
# the plain release version is tagged here.
if [[ ! "$version" =~ ^[0-9]+(\.[0-9]+){2,3}$ ]]; then
    printf '%s in pyproject.toml is not a plain release version.\n' "$version" >&2
    printf 'Release candidates are published with ./scripts/release/010_pre_release.sh,\n' >&2
    printf 'which tags the current commit without touching pyproject.toml.\n' >&2
    exit 1
fi

tag="v$version"

# An existing tag may point at an older commit, for example when it was created
# before further work landed. Report both commits and let the developer decide;
# never move a tag silently, because that rewrites what the release contains.
existing_local="$(git rev-parse -q --verify "refs/tags/$tag^{commit}" || true)"
existing_remote=""
if [[ "$local_only" != true ]] && \
    git ls-remote --exit-code --tags origin "refs/tags/$tag^{}" >/dev/null 2>&1; then
    existing_remote="$(git ls-remote --tags origin "refs/tags/$tag^{}" | cut -f1)"
fi

if [[ -n "$existing_local" || -n "$existing_remote" ]]; then
    printf '\nThe tag %s already exists.\n\n' "$tag" >&2
    printf '  Tag points at:   %s %s\n' "${existing_local:0:12}" \
        "$(git log -1 --pretty=%s "$existing_local" 2>/dev/null)" >&2
    if [[ -n "$existing_remote" && "$existing_remote" != "$existing_local" ]]; then
        printf '  On origin:       %s\n' "${existing_remote:0:12}" >&2
    fi
    printf '  Current commit:  %s %s\n' "${sha:0:12}" "$(git log -1 --pretty=%s "$sha")" >&2

    if [[ -n "$existing_local" && "$existing_local" == "$sha" ]]; then
        printf '\nNothing to do: the tag already points at the current commit.\n' >&2
        exit 0
    fi

    printf '\nChoose how to continue:\n' >&2
    printf '  1. Leave the existing tag as it is.\n' >&2
    printf '     The release for %s is already published from the older commit.\n' "$version" >&2
    printf '  2. Move the tag to the current commit (rewrites the published release).\n' >&2
    printf '       git tag -fa %s -m %s && git push origin %s --force\n' \
        "$tag" "$tag" "$tag" >&2
    printf '  3. Release a different version instead: update the version in\n' >&2
    printf '     pyproject.toml on a branch, merge it, and run this script again.\n' >&2
    printf '\nThis script does not move or delete tags on its own.\n' >&2
    exit 1
fi

mapfile -t release_tags_at_commit < <(git tag --points-at "$sha" --list 'v*')
unexpected_release_tags=()
for release_tag in "${release_tags_at_commit[@]}"; do
    if [[ "$release_tag" =~ ^v([0-9]+\.[0-9]+\.[0-9]+(\.[0-9]+)?)-rc\.[0-9]+$ ]] && \
        [[ "${BASH_REMATCH[1]}" == "$version" ]]; then
        continue
    fi
    unexpected_release_tags+=("$release_tag")
done
if ((${#unexpected_release_tags[@]})); then
    printf 'Commit %s already has release tag(s): %s\n' \
        "${sha:0:12}" "${unexpected_release_tags[*]}" >&2
    echo "Only a matching release-candidate tag may share the final-release commit." >&2
    exit 1
fi

printf '\nFinal release plan\n'
printf '  Project:      %s\n' "$project_root"
printf '  Branch:       %s%s\n' "$branch" \
    "$(if [[ "$branch" == "$current_branch" ]]; then echo " (checked out)"; else echo ""; fi)"
printf '  Commit:       %s\n' "${sha:0:12}"
printf '  Version:      %s (from pyproject.toml)\n' "$version"
printf '  Tag:          %s (published release, becomes latest)\n' "$tag"
printf '  Fetch:        %s\n' "$(if [[ "$fetch" == true ]]; then echo "yes"; else echo "no"; fi)"
printf '  Push:         %s\n' "$(if [[ "$push" == true ]]; then echo "tag only"; else echo "no"; fi)"
if [[ "$local_only" == true ]]; then
    printf '  Tag scope:    local refs only; remote tags and CI status are unknown\n'
fi
if [[ "$branch" != "$default_branch" ]]; then
    printf '  Note:         --branch selected non-default branch %s (default: %s).\n' \
        "$branch" "$default_branch"
fi

# Report the CI status of the commit that is about to be tagged.
repository=""
if [[ "$local_only" != true ]] && command -v gh >/dev/null 2>&1; then
    repository="$(gh repo view --json nameWithOwner --jq .nameWithOwner 2>/dev/null || true)"
fi
checks=""
if [[ "$local_only" != true && -n "$repository" ]]; then
    checks="$(gh api "repos/$repository/commits/$sha/check-runs?per_page=100" \
        --jq '[.check_runs[] | "\(.name): \(.status)/\(.conclusion // "running")"] | .[]' 2>/dev/null || true)"
fi

if [[ "$local_only" == true ]]; then
    printf '  CI checks:    not checked for local-only tag\n'
elif [[ -z "$checks" ]]; then
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
    if [[ "$local_only" == true ]]; then
        printf 'Tag %s created locally; no remote action was taken.\n' "$tag"
    else
        printf 'Tag %s created locally. Push it with:\n' "$tag"
        printf '  git push origin %s\n' "$tag"
    fi
fi
