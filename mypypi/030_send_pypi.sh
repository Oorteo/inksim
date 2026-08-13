#!/usr/bin/bash
# Upload the built distributions to PyPI using Twine.
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

# install twine: uv tool install twine
# upload to pypi  (check you have valid token, ~/.pypirc
shopt -s nullglob
artifacts=("$project_root"/dist/*)
if ((${#artifacts[@]} == 0)); then
    echo "No distributions found in $project_root/dist; run mypypi/010_build.sh first." >&2
    exit 1
fi

printf '\nUpload plan for: %s\n' "$project_root"
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
