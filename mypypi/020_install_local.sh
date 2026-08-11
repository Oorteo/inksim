#!/usr/bin/env bash
# Install the locally built wheel as an isolated uv tool; no PyPI upload occurs.
# Runs on macOS, Linux, or Windows via Bash (Git Bash/WSL).

# We want to execute: uv tool install ....

set -euo pipefail
set -x

source_path="${BASH_SOURCE[0]}"
# Resolve symlinks portably; this is the Bash equivalent of readlink -f.
while [[ -L "$source_path" ]]; do
    script_dir="$(cd -P "$(dirname "$source_path")" && pwd)"
    source_path="$(readlink "$source_path")"
    [[ "$source_path" = /* ]] || source_path="$script_dir/$source_path"
done
script_dir="$(cd -P "$(dirname "$source_path")" && pwd)"
project_root="$(cd -- "$script_dir/.." && pwd)"
python_version="${PYTHON_VERSION:-3.14}"

shopt -s nullglob
wheels=("$project_root"/dist/inksim-*.whl)
if ((${#wheels[@]} != 1)); then
    echo "Expected exactly one wheel in $project_root/dist; run mypypi/010_build.sh first." >&2
    exit 1
fi

install_options=(--force --reinstall --python "$python_version")
if [[ "$(uname -s)" == Linux ]]; then
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
    install_options+=(--find-links "$wxpython_url")
fi

printf 'Installing local wheel: %s\n' "${wheels[0]}"
printf 'wxPython source: %s\n' "${wxpython_url:-PyPI}"

exec uv tool install "${install_options[@]}" "${wheels[0]}"
