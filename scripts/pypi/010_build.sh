#!/usr/bin/bash
# Prepare the README for PyPI and build the project package.
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

# Build packages for PyPI
# clean dist
rm -rf dist/
rm -rf build/

# PyPI renders the README outside the repository, so relative documentation
# links do not work there. Build it with links to the current Git ref while
# keeping the checked-out README unchanged. Set INKSIM_DOCS_REF to a tag or
# another stable ref when building a release.
docs_ref="${INKSIM_DOCS_REF:-$(git branch --show-current)}"
if [[ -z "$docs_ref" ]]; then
    docs_ref="$(git rev-parse --short HEAD)"
fi

printf '\nBuild plan for: %s\n' "$project_root"
printf '  Remove existing dist/ and build/ directories.\n'
printf '  Prepare README links for PyPI temporarily.\n'
printf '  Build the package with uv.\n'
if [[ "$assume_yes" != true ]]; then
    printf 'Continue? [y/N] '
    read -r answer
    [[ "$answer" =~ ^[Yy]$ ]] || {
        printf 'Build cancelled.\n'
        exit 0
    }
fi

set -x
readme_backup="$(mktemp)"
cp "$project_root/README.md" "$readme_backup"
trap 'cp "$readme_backup" "$project_root/README.md"; rm -f "$readme_backup"' EXIT

uv run python - "$project_root/README.md" "$docs_ref" <<'PY'
import re
import sys
from pathlib import Path
from urllib.parse import quote


readme_path = Path(sys.argv[1])
docs_ref = quote(sys.argv[2], safe="/")
text = readme_path.read_text()
github_root = f"https://github.com/karnigen/inksim/blob/{docs_ref}/"
raw_root = f"https://raw.githubusercontent.com/karnigen/inksim/{docs_ref}/"
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

uv build
