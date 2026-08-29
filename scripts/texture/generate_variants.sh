#!/usr/bin/env bash
# Generate all thread texture variants with clear, descriptive names.
#
# Each variant is rendered into ./renders/<variant>/ with files named
# thread_<variant>_<map>.png (diffuse/normal/mask/normal_mask/roughness/height/rgba).
# ./renders/ is regenerable output and is not committed to git.
#
# The renderer only loads ONE packaged file at runtime:
#   src/inksim/assets/thread_textures/<DEFAULT_VARIANT>_normal_mask.png
# so after generating, the chosen default variant's normal_mask map is copied
# there. Change DEFAULT_VARIANT below (and inksim/render/stitches_gl.py's
# _default_texture_path) to ship a different look.
set -euo pipefail
cd "$(dirname "$0")"

SCRIPT="thread_texture.py"
OUT_ROOT="renders"
ASSETS_DIR="../../src/inksim/assets/thread_textures"
DEFAULT_VARIANT="classic_3strand"

rm -rf "$OUT_ROOT"
mkdir -p "$OUT_ROOT"

generate() {
    local name="$1"
    shift
    echo "==> $name"
    uvr python "$SCRIPT" --output-dir "$OUT_ROOT/$name" --prefix "$name" "$@"
}

generate classic_3strand --strands 3
generate soft_2strand --strands 2 --strand-radius 28 --helix-radius 14 --blend-softness 3.5
generate bold_4strand --strands 4 --strand-radius 20 --helix-radius 10 --blend-softness 2.0

mkdir -p "$ASSETS_DIR"
cp "$OUT_ROOT/$DEFAULT_VARIANT/${DEFAULT_VARIANT}_normal_mask.png" "$ASSETS_DIR/"
echo "Copied ${DEFAULT_VARIANT}_normal_mask.png -> $ASSETS_DIR (packaged asset used by the renderer)"
