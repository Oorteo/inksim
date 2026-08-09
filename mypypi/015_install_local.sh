#!/usr/bin/env bash
# Install the locally built wheel as an isolated uv tool; no PyPI upload occurs.
set -euo pipefail
set -x

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
project_root="$(cd -- "$script_dir/.." && pwd)"
python_version="${PYTHON_VERSION:-3.12}"

shopt -s nullglob
wheels=("$project_root"/dist/inksim-*.whl)
if ((${#wheels[@]} != 1)); then
    echo "Expected exactly one wheel in $project_root/dist; run mypypi/010_build.sh first." >&2
    exit 1
fi

if [[ -z "${WXPYTHON_PLATFORM:-}" ]]; then
    [[ -r /etc/os-release ]] || {
        echo "Cannot detect the Linux distribution; set WXPYTHON_PLATFORM manually." >&2
        exit 1
    }

    source /etc/os-release
    case "${ID:-}" in
    ubuntu) WXPYTHON_PLATFORM="ubuntu-${VERSION_ID}" ;;
    linuxmint)
        case "${UBUNTU_CODENAME:-}" in
        noble) WXPYTHON_PLATFORM=ubuntu-24.04 ;;
        jammy) WXPYTHON_PLATFORM=ubuntu-22.04 ;;
        focal) WXPYTHON_PLATFORM=ubuntu-20.04 ;;
        *) WXPYTHON_PLATFORM= ;;
        esac
        ;;
    centos | debian | fedora | rocky) WXPYTHON_PLATFORM="${ID}-${VERSION_ID%%.*}" ;;
    *) WXPYTHON_PLATFORM= ;;
    esac
fi

[[ -n "$WXPYTHON_PLATFORM" ]] || {
    echo "Unsupported Linux distribution; set WXPYTHON_PLATFORM manually." >&2
    exit 1
}

wxpython_url="https://extras.wxpython.org/wxPython4/extras/linux/gtk3/$WXPYTHON_PLATFORM"
printf 'Installing local wheel: %s\n' "${wheels[0]}"
printf 'wxPython source: %s\n' "$wxpython_url"

exec uv tool install --force --reinstall --python "$python_version" \
    --find-links "$wxpython_url" "${wheels[0]}"
