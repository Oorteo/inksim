#!/usr/bin/bash
set -euo pipefail

# get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"

# uv-ubuntu-24.04:

pushd "$SCRIPT_DIR/.." &>/dev/null

uv python pin 3.12
uv venv
uv pip install -U -f https://extras.wxpython.org/wxPython4/extras/linux/gtk3/ubuntu-24.04 wxPython==4.2.5
# overwrite the wxPython version to 4.2.5 in the lock file, so that uv doesn't try to upgrade it to 4.3.0 when syncing
uv lock --find-links https://extras.wxpython.org/wxPython4/extras/linux/gtk3/ubuntu-24.04 --exclude-newer-package wxPython=2026-01-01
uv sync

popd &>/dev/null
