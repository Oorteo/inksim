#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later
#
### Generate all thread texture variants with clear, descriptive names.
###
### Each variant is rendered into ./renders/<variant>/ with files named
### <variant>_<map>.png (diffuse/normal/mask/normal_mask/roughness/height/rgba)
### plus a <variant>_manifest.json describing its parameters and measured
### width_fraction. ./renders/ is regenerable output and is not committed to git.
###
### The renderer loads the packaged assets under
###   src/inksim/assets/thread_textures/
### so after generating, every variant's normal_mask map AND manifest are copied
### there (the manifest carries the width_fraction used to normalise thickness).
### Change DEFAULT_VARIANT below (and inksim/render/stitches_gl.py's
### _default_texture_path) to ship a different default look.
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
    ### Use 528 px width so all default twist_periods (2, 3, 6) divide evenly:
    ###   528/2 = 264, 528/3 = 176, 528/6 = 88.
    ### This removes the small rounding error that 512 px introduced.
    uvr "$SCRIPT" --output-dir "$OUT_ROOT/$name" --prefix "$name" --width 528 --tile-preview "$@"
}

### Variants are deliberately spread wide so the visual differences are obvious.
generate classic_3strand --strands 3
generate soft_2strand --strands 2 --strand-radius 28 --helix-radius 14 --blend-softness 3.5
generate bold_4strand --strands 4 --strand-radius 20 --helix-radius 10 --blend-softness 2.0
generate thin_2strand --strands 2 --strand-radius 16 --helix-radius 8 --blend-softness 2.0
generate thick_6strand --strands 6 --strand-radius 18 --helix-radius 12 --blend-softness 1.5
generate tight_twist --strands 3 --twist-periods 6
generate loose_twist --strands 3 --twist-periods 2
generate fuzzy_3strand --strands 3 --fiber-noise 0.14

### gap_2strand: two strands that barely touch, leaving a narrow air gap. The
### spacing is small (4 px) so the gap is subtle, not two separate ropes.
generate gap_2strand --strands 2 --strand-spacing 12 --strand-radius 22 --helix-radius 12 --blend-softness 2.0

mkdir -p "$ASSETS_DIR"
for variant_dir in "$OUT_ROOT"/*/; do
    name="$(basename "$variant_dir")"
    cp "$variant_dir/${name}_normal_mask.png" "$ASSETS_DIR/"
    cp "$variant_dir/${name}_manifest.json" "$ASSETS_DIR/"
    cp "$variant_dir/${name}_cap_mask.png" "$ASSETS_DIR/"
    echo "Copied ${name}_normal_mask.png + cap_mask + manifest -> $ASSETS_DIR"
done
echo "Default variant: $DEFAULT_VARIANT"
