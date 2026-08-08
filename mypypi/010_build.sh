#!/usr/bin/bash
set -e
set -x

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
project_root="$(cd -- "$script_dir/.." && pwd)"
cd "$project_root"
pwd

# build packages for pypi
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
