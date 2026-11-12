#!/usr/bin/bash
# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Build release distributions from the exact version tag.
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
cd "$project_root"
pwd

git rev-parse --git-dir >/dev/null 2>&1 || {
    echo "$project_root is not a Git repository." >&2
    exit 1
}

mapfile -t release_tags < <(git tag --points-at HEAD --list 'v*')
if ((${#release_tags[@]} != 1)); then
    echo "Expected exactly one v* release tag pointing at HEAD." >&2
    if ((${#release_tags[@]} == 0)); then
        echo "Create or check out a release tag before building." >&2
    else
        printf 'Found multiple tags: %s\n' "${release_tags[*]}" >&2
    fi
    exit 1
fi
tag="${release_tags[0]}"

if [[ "$tag" =~ ^v([0-9]+\.[0-9]+\.[0-9]+(\.[0-9]+)?)-rc\.([0-9]+)$ ]]; then
    release_version="${BASH_REMATCH[1]}"
    distribution_version="${release_version}rc${BASH_REMATCH[3]}"
    is_prerelease=true
elif [[ "$tag" =~ ^v([0-9]+\.[0-9]+\.[0-9]+(\.[0-9]+)?)$ ]]; then
    distribution_version="${BASH_REMATCH[1]}"
    is_prerelease=false
else
    printf 'Unsupported release tag format: %s\n' "$tag" >&2
    exit 1
fi

printf '\nBuild plan for: %s\n' "$project_root"
printf '  Tag:          %s\n' "$tag"
printf '  Version:      %s\n' "$distribution_version"
printf '  Channel:      %s\n' "$(if [[ "$is_prerelease" == true ]]; then echo "pre-release"; else echo "stable"; fi)"
printf '  Remove existing dist/ and build/ directories.\n'
printf '  Build from the tagged source in a temporary directory.\n'
if [[ "$is_prerelease" == true ]]; then
    printf '  PyPI upload:  blocked; use the GitHub pre-release instead.\n'
fi
if [[ "$assume_yes" != true ]]; then
    printf 'Continue? [y/N] '
    read -r answer
    [[ "$answer" =~ ^[Yy]$ ]] || {
        printf 'Build cancelled.\n'
        exit 0
    }
fi

rm -rf "$project_root/dist" "$project_root/build"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT
build_root="$tmp_dir/source"
mkdir -p "$build_root"
git archive "$tag" | tar -xf - -C "$build_root"

uv run python - "$build_root/README.md" "$tag" <<'PY'
import re
import sys
from pathlib import Path
from urllib.parse import quote


readme_path = Path(sys.argv[1])
docs_ref = quote(sys.argv[2], safe="/")
text = readme_path.read_text()
github_root = f"https://github.com/oorteo/inksim/blob/{docs_ref}/"
raw_root = f"https://raw.githubusercontent.com/oorteo/inksim/{docs_ref}/"
scheme_pattern = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
image_suffixes = (".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp")


def convert_target(target):
    if not target or target.startswith(("#", "/", "\\")):
        return target
    if scheme_pattern.match(target) or target.startswith("//"):
        return target

    match = re.match(r"([^#?]*)(.*)$", target)
    path, suffix = match.groups()
    encoded_path = quote(path.lstrip("./"), safe="/._-~")
    root = raw_root if path.lower().endswith(image_suffixes) else github_root
    return f"{root}{encoded_path}{suffix}"


def replace_markdown_link(match):
    return f"{match.group(1)}{convert_target(match.group(2))}{match.group(3)}"


link_pattern = re.compile(r"(\]\()([^\s()<]+)(\))")
text = link_pattern.sub(replace_markdown_link, text)


def replace_html_source(match):
    return f"{match.group(1)}{convert_target(match.group(2))}{match.group(3)}"


source_pattern = re.compile(r"(\bsrc=[\"'])([^\"']+)([\"'])", re.IGNORECASE)
text = source_pattern.sub(replace_html_source, text)
readme_path.write_text(text)
PY

(
    cd "$build_root"
    uv version "$distribution_version" --no-sync
    uv build
)

shopt -s nullglob
built_artifacts=("$build_root"/dist/*.whl "$build_root"/dist/*.tar.gz)
if ((${#built_artifacts[@]} == 0)); then
    echo "The tagged source did not produce any distributions." >&2
    exit 1
fi
mkdir -p "$project_root/dist"
cp "${built_artifacts[@]}" "$project_root/dist/"
printf '\nBuilt distributions from %s:\n' "$tag"
for artifact in "${built_artifacts[@]}"; do
    printf '  dist/%s\n' "${artifact##*/}"
done
