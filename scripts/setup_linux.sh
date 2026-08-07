#!/usr/bin/bash
# Set up the project's uv environment and install the matching wxPython build.
set -euo pipefail

[[ "$(uname -s)" == Linux ]] || {
    echo "This script only supports Linux" >&2
    exit 1
}

case "${1:-}" in
"") CLEAN_VENV=false ;;
-y | --yes) CLEAN_VENV=true ;;
*)
    echo "Usage: $0 [-y|--yes]" >&2
    exit 1
    ;;
esac

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
PYTHON_VERSION="${PYTHON_VERSION:-3.12}"
WXPYTHON_VERSION="${WXPYTHON_VERSION:-4.2.5}"

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
centos | debian | fedora | rocky)
    WXPYTHON_PLATFORM="$ID-${VERSION_ID%%.*}"
    ;;
*) WXPYTHON_PLATFORM= ;;
esac
[[ -n "$WXPYTHON_PLATFORM" ]] || {
    echo "Unsupported Linux distribution: ${ID:-unknown} ${VERSION_ID:-}" >&2
    exit 1
}
WXPYTHON_URL="https://extras.wxpython.org/wxPython4/extras/linux/gtk3/$WXPYTHON_PLATFORM"

cd "$SCRIPT_DIR/.."
VENV_PATH="$PWD/.venv"
UV_PATH="$(command -v uv || true)"
[[ -n "$UV_PATH" ]] || {
    echo "uv is required" >&2
    exit 1
}

printf '\nDetected configuration:\n'
printf '  OS:              %s\n' "${PRETTY_NAME:-unknown}"
printf '  ID:              %s\n' "${ID:-unknown}"
printf '  ID like:         %s\n' "${ID_LIKE:-none}"
printf '  OS version:      %s\n' "${VERSION_ID:-unknown}"
printf '  Ubuntu codename: %s\n' "${UBUNTU_CODENAME:-${VERSION_CODENAME:-none}}"
printf '  wxPython target: %s\n' "$WXPYTHON_PLATFORM"
printf '  wxPython URL:    %s\n' "$WXPYTHON_URL"
printf '  Python:          %s\n' "$PYTHON_VERSION"
printf '  wxPython:        %s\n' "$WXPYTHON_VERSION"
printf '  uv:              %s\n' "$UV_PATH"
printf '  Project:         %s\n' "$PWD"
printf '  Virtual env:     %s\n' "$VENV_PATH"
printf '  Clean .venv:     %s\n\n' "$CLEAN_VENV"

if [[ "$CLEAN_VENV" == true ]]; then
    echo "Removing virtual environment: $VENV_PATH"
    rm -rf "$VENV_PATH"
elif [[ -d "$VENV_PATH" ]]; then
    echo "Found virtual environment: $VENV_PATH"
    read -r -p "Set it up again? [y/N] " answer
    [[ "$answer" =~ ^[Yy]$ ]] || exit 0
else
    echo "Virtual environment will be created at: $VENV_PATH"
    read -r -p "Set up uv environment? [Y/n] " answer
    [[ "$answer" =~ ^[Nn]$ ]] && exit 0
fi

uv python pin "$PYTHON_VERSION"
[[ -d "$VENV_PATH" ]] || uv venv
uv pip install -U -f "$WXPYTHON_URL" "wxPython==$WXPYTHON_VERSION"
uv lock --find-links "$WXPYTHON_URL" --exclude-newer-package wxPython=2026-01-01
uv sync
