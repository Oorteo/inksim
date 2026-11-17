#!/usr/bin/bash
# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Upload the built distributions to PyPI using Twine.
set -euo pipefail

assume_yes=false
allow_non_main=false
while (($#)); do
    case "$1" in
    -y | --yes) assume_yes=true ;;
    --allow-non-main) allow_non_main=true ;;
    -h | --help)
        printf 'Usage: %s [-y|--yes] [--allow-non-main]\n' "$0"
        exit 0
        ;;
    *)
        printf 'Usage: %s [-y|--yes] [--allow-non-main]\n' "$0" >&2
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
# Find the project root instead of assuming this script is one level below it.
project_root="$script_dir"
while [[ ! -f "$project_root/pyproject.toml" && "$project_root" != "/" ]]; do
    project_root="$(cd -- "$project_root/.." && pwd)"
done
[[ -f "$project_root/pyproject.toml" ]] || {
    echo "Could not find pyproject.toml above $script_dir." >&2
    exit 1
}

cd "$project_root"
pwd

git rev-parse --git-dir >/dev/null 2>&1 || {
    echo "$project_root is not a Git repository." >&2
    exit 1
}

mapfile -t release_tags < <(git tag --points-at HEAD --list 'v*')
if ((${#release_tags[@]} != 1)); then
    echo "PyPI upload requires exactly one v* release tag pointing at HEAD." >&2
    exit 1
fi
tag="${release_tags[0]}"
if [[ "$tag" =~ ^v([0-9]+\.[0-9]+\.[0-9]+(\.[0-9]+)?)$ ]]; then
    release_version="${BASH_REMATCH[1]}"
else
    printf 'PyPI upload is only allowed from a stable release tag; refusing %s.\n' "$tag" >&2
    echo "Pre-releases are distributed through GitHub Releases, not PyPI." >&2
    exit 1
fi

default_branch="$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null | sed 's|^origin/||')"
default_branch="${default_branch:-main}"
default_branch_ref="refs/remotes/origin/$default_branch"
if [[ "$allow_non_main" == true ]]; then
    echo "WARNING: --allow-non-main bypasses the main-branch check; this still uploads to PyPI." >&2
else
    if ! git show-ref --verify --quiet "$default_branch_ref"; then
        printf 'Cannot verify the release against origin/%s.\n' "$default_branch" >&2
        printf 'Fetch the default branch or pass --allow-non-main for an exceptional upload.\n' >&2
        exit 1
    fi
    if ! git merge-base --is-ancestor HEAD "$default_branch_ref"; then
        printf 'PyPI uploads are restricted to commits reachable from origin/%s.\n' \
            "$default_branch" >&2
        echo "For an exceptional non-main upload, pass --allow-non-main." >&2
        exit 1
    fi
fi

# install twine: uv tool install twine
# upload to pypi  (check you have valid token, ~/.pypirc
shopt -s nullglob
artifacts=("$project_root"/dist/*.whl "$project_root"/dist/*.tar.gz)
if ((${#artifacts[@]} == 0)); then
    echo "No distributions found in $project_root/dist; run scripts/pypi/010_build.sh first." >&2
    exit 1
fi
for artifact in "${artifacts[@]}"; do
    filename="${artifact##*/}"
    case "$filename" in
    "inksim-$release_version-"*.whl | "inksim-$release_version.tar.gz") ;;
    *)
        printf 'Artifact %s does not match stable release tag %s; refusing upload.\n' \
            "$filename" "$tag" >&2
        exit 1
        ;;
    esac
done

printf '\nUpload plan for: %s\n' "$project_root"
printf '  Stable tag: %s\n' "$tag"
printf '  Default branch: origin/%s\n' "$default_branch"
printf '  Upload the following distribution(s) to PyPI:\n'
for artifact in "${artifacts[@]}"; do
    printf '    %s\n' "${artifact#"$project_root"/}"
done
if [[ "$assume_yes" != true ]]; then
    printf 'Continue with PyPI upload? [y/N] '
    read -r answer
    [[ "$answer" =~ ^[Yy]$ ]] || {
        printf 'Upload cancelled.\n'
        exit 0
    }
fi

set -x
twine upload "${artifacts[@]}"
