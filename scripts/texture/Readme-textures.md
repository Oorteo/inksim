# GPU Thread Texture Assets

This folder contains procedural texture generation for the GPU embroidery-thread renderer.

## Files

| Path                   | Purpose                                                                                   |
| ---------------------- | ----------------------------------------------------------------------------------------- |
| `thread_texture.py`    | Procedural PBR texture generator (one variant per run).                                   |
| `generate_variants.sh` | Generates every named variant below and refreshes the packaged app asset. Run this first. |
| `renders/<variant>/`   | Generated output, one subfolder per variant. Regenerable, **not committed to git**.       |

## Naming

Every generated file is named `<variant>_<map>.png` (the `--prefix` passed to
the generator is the full variant name), e.g. `classic_3strand_diffuse.png`.
`<variant>` is a descriptive style name (not a version number), currently:

| Variant           | Look                                                                           |
| ----------------- | ------------------------------------------------------------------------------ |
| `classic_3strand` | Default 3-strand twisted thread. **This is the variant shipped with the app.** |
| `soft_2strand`    | Thicker, softer 2-strand thread.                                               |
| `bold_4strand`    | Thicker 4-strand thread.                                                       |
| `thin_2strand`    | Thin 2-strand thread.                                                          |
| `thick_6strand`   | Thick 6-strand thread.                                                         |
| `tight_twist`     | 3-strand thread with doubled twist density.                                    |
| `loose_twist`     | 3-strand thread with a slow, loose twist.                                      |
| `fuzzy_3strand`   | 3-strand thread with heavy fibre fuzz.                                         |

## Quick start

Regenerate all variants and refresh the packaged asset in one step:

```bash
cd scripts/texture
./generate_variants.sh
```

This writes each variant's full map set to `renders/<variant>/`, then copies
every variant's `normal_mask.png`, `cap_mask.png` and manifest JSON to
`src/inksim/assets/thread_textures/` (see `generate_variants.sh`). The
currently active variant is set in `_default_texture_path()` in
`src/inksim/render/stitches_gl.py`; the renderer reads its sibling manifest
for `width_fraction` (ribbon-width normalisation) and `cap_radius_fraction`
(end-cap overshoot).

To ship a different variant, either change `DEFAULT_VARIANT` in
`generate_variants.sh` and `_default_texture_path()` together, or generate a
one-off set manually:

```bash
uvr python thread_texture.py --strands 3 --output-dir ./my_textures --prefix my_thread
```

## Output maps

| Suffix             | Channels  | Use in the renderer                                                                                                         |
| ------------------ | --------- | --------------------------------------------------------------------------------------------------------------------------- |
| `_diffuse.png`     | RGB       | Albedo / base colour. Not used by the live GL renderer (it uses the stitch colour instead).                                 |
| `_normal.png`      | RGB       | Normal map in OpenGL convention `(normal * 0.5 + 0.5)`, **no alpha channel**.                                               |
| `_mask.png`        | Grayscale | Alpha mask: white = thread, black = gap.                                                                                    |
| `_normal_mask.png` | RGBA      | **The file the GL renderer loads.** RGB = normal map, A = real alpha mask (transparent gaps).                               |
| `_cap_mask.png`    | Grayscale | **Semicircular end-cap mask.** White = keep thread, black = trim. Trimmed to a rounded arc at both stitch ends (see below). |
| `_roughness.png`   | Grayscale | PBR roughness (unused by the current renderer).                                                                             |
| `_height.png`      | Grayscale | Displacement / height (unused by the current renderer).                                                                     |
| `_rgba.png`        | RGBA      | Quick preview with baked diffuse colour + alpha (for looking at the texture, not for GL).                                   |
| `_manifest.json`   | JSON      | Variant parameters plus measured `width_fraction` and `cap_radius_fraction`.                                                |

## The end-cap mask (`_cap_mask.png`)

Stitches must not end in a hard vertical cut: each stitch is extended a
little beyond its needle points and trimmed to a **semicircular arc** by the
cap mask. The arc's radius is measured from the generated alpha mask (helix
swing + strand thickness + fibre fuzz), so every variant gets its own
matching end shape; the measured radius / canvas height is stored as
`cap_radius_fraction` in the manifest.

The renderer uses the mask like this:

1. Each stitch ribbon is extended past both needle points by
   `cap_radius_fraction * ribbon height` (the "tip" zones).
2. The uploaded cap texture holds **two copies** of the semicircle side by
   side -- `[as-generated | U-flipped]` -- whose middle seam joins the two
   flat white sides. The ribbon body samples that white seam column (alpha
   untouched); each tip sweeps mu outward into its half, so the arc trims
   the tip to a rounded end. The two tips at a shared needle point sample
   the same U-phase window, like overlapping real threads.
3. `alpha = thread_alpha * cap_mask` in the fragment shader; both stitch
   ends come out as symmetric semicircular arcs.

Details of the geometry and UV mapping: see `thread_texture-explained.md`
(sections 5 and 8).

## Tuning the thread look

The most important parameters:

- `--strands` – number of twisted strands (2-4 look natural for embroidery thread).
- `--strand-radius` – thickness of one strand in pixels.
- `--helix-radius` – how far strands spiral around the core.
- `--twist-periods` (alias `--twist-period`) – number of twists across the texture width.
- `--blend-softness` – how hard/soft the strand crossover edges are.
- `--fiber-noise` – amount of micro fibre detail.
- `--color-top` / `--color-mid` / `--color-bottom` – baked-lighting colours for the `_diffuse`/`_rgba` preview (ignored by the live GL renderer).

## Integration with the renderer

`src/inksim/render/stitches_gl.py` (used by both the offscreen exporter and the
live `GLStitchWidget`) loads **two** textures per variant:

- `<variant>_normal_mask.png`:
    - `rgb` is sampled as the tangent-space normal.
    - `a` is the real alpha mask -- pixels below the threshold are discarded, so
      gaps between thread strands are transparent instead of covering
      neighbouring stitches.
- `<variant>_cap_mask.png` (sibling of the normal mask): the semicircular
  end-cap mask, doubled/flip-arranged by the renderer as described above and
  bound as a second sampler (`u_cap_mask`).

The sibling `<variant>_manifest.json` is also read: `width_fraction`
normalises the ribbon width so all variants render at the same physical
thickness; `cap_radius_fraction` tells the renderer how far to extend each
stitch past its needle points before the cap mask trims the tip.

If you add a new style, regenerate via `generate_variants.sh` (or a manual
`thread_texture.py` run) and update `DEFAULT_VARIANT` / `_default_texture_path()`
to point at it.

## Notes

- The generator bakes lighting into the diffuse/rgba maps for quick human preview only; the live renderer never reads them.
- Colour arguments are comma-separated `R,G,B` integers in `[0, 255]`.
- The texture tiles in the **U direction** (along the stitch) and clamps in the **V direction** (across the thread).
