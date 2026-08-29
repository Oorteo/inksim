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

## Quick start

Regenerate all variants and refresh the packaged asset in one step:

```bash
cd scripts/texture
./generate_variants.sh
```

This writes each variant's full map set to `renders/<variant>/`, then copies
`renders/classic_3strand/classic_3strand_normal_mask.png` to
`src/inksim/assets/thread_textures/` -- the only file the GL renderer actually
loads at runtime (see `_default_texture_path()` in
`src/inksim/render/stitches_gl.py`).

To ship a different variant, either change `DEFAULT_VARIANT` in
`generate_variants.sh` and `_default_texture_path()` together, or generate a
one-off set manually:

```bash
uv run python thread_texture.py --strands 3 --output-dir ./my_textures --prefix my_thread
```

## Output maps

| Suffix             | Channels  | Use in the renderer                                                                           |
| ------------------ | --------- | --------------------------------------------------------------------------------------------- |
| `_diffuse.png`     | RGB       | Albedo / base colour. Not used by the live GL renderer (it uses the stitch colour instead).   |
| `_normal.png`      | RGB       | Normal map in OpenGL convention `(normal * 0.5 + 0.5)`, **no alpha channel**.                 |
| `_mask.png`        | Grayscale | Alpha mask: white = thread, black = gap.                                                      |
| `_normal_mask.png` | RGBA      | **The file the GL renderer loads.** RGB = normal map, A = real alpha mask (transparent gaps). |
| `_roughness.png`   | Grayscale | PBR roughness (unused by the current renderer).                                               |
| `_height.png`      | Grayscale | Displacement / height (unused by the current renderer).                                       |
| `_rgba.png`        | RGBA      | Quick preview with baked diffuse colour + alpha (for looking at the texture, not for GL).     |

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
live `GLStitchWidget`) loads a single `_normal_mask.png`:

- `rgb` is sampled as the tangent-space normal.
- `a` is the real alpha mask -- pixels below the threshold are discarded, so
  gaps between thread strands are transparent instead of covering
  neighbouring stitches.

If you add a new style, regenerate via `generate_variants.sh` (or a manual
`thread_texture.py` run) and update `DEFAULT_VARIANT` / `_default_texture_path()`
to point at it.

## Notes

- The generator bakes lighting into the diffuse/rgba maps for quick human preview only; the live renderer never reads them.
- Colour arguments are comma-separated `R,G,B` integers in `[0, 255]`.
- The texture tiles in the **U direction** (along the stitch) and clamps in the **V direction** (across the thread).
