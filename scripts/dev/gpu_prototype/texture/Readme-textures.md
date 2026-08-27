# GPU Thread Texture Assets

This folder contains procedural texture generation for the GPU embroidery-thread renderer.

## Files

| File                                       | Purpose                                                                                                    |
| ------------------------------------------ | ---------------------------------------------------------------------------------------------------------- |
| `thread_texture.py`                        | Procedural PBR texture generator. Produces diffuse, normal, mask, roughness, height and RGBA preview maps. |
| `thread_textures_3/`                       | Example output for a **3-strand** twisted thread.                                                          |
| `thread_textures_2/`, `thread_textures_4/` | Older example outputs kept for comparison.                                                                 |

## Quick start

Generate a default 3-strand texture set:

```bash
cd scripts/dev/gpu_prototype/texture
uv run python thread_texture.py --strands 3 --output-dir ./my_textures
```

## Output maps

| Suffix           | Channels  | Use in the renderer                                                                    |
| ---------------- | --------- | -------------------------------------------------------------------------------------- |
| `_diffuse.png`   | RGB       | Albedo / base colour (can be ignored if the renderer uses the stitch colour directly). |
| `_normal.png`    | RGB       | Normal map in OpenGL convention `(normal * 0.5 + 0.5)`.                                |
| `_mask.png`      | Grayscale | Alpha mask: white = thread, black = gap.                                               |
| `_roughness.png` | Grayscale | PBR roughness.                                                                         |
| `_height.png`    | Grayscale | Displacement / height.                                                                 |
| `_rgba.png`      | RGBA      | Quick preview with baked diffuse + alpha.                                              |

## Tuning the thread look

The most important parameters are:

- `--strands` – number of twisted strands (2 or 3 look natural for embroidery thread).
- `--strand-radius` – thickness of one strand in pixels.
- `--helix-radius` – how far strands spiral around the core.
- `--period` – twist period in pixels (along the stitch direction).
- `--blend-softness` – how hard/soft the strand crossover edges are.
- `--fiber-noise` – amount of micro fibre detail.

Example: thicker, softer 2-strand thread:

```bash
uv run python thread_texture.py \
    --strands 2 \
    --strand-radius 28 \
    --helix-radius 14 \
    --period 256 \
    --blend-softness 3.5 \
    --output-dir ./thread_textures_2
```

Example: red thread with custom colours:

```bash
uv run python thread_texture.py \
    --strands 3 \
    --color-top "255,200,200" \
    --color-mid "200,80,80" \
    --color-bottom "120,30,30" \
    --output-dir ./red_thread
```

## Integration with the renderer

The GPU prototype `../ds_gpu_thread_v2.py` expects a single-channel RGBA normal map where:

- `rgb` encodes the tangent-space normal.
- `a` encodes the thread mask.

Pass the generated `_normal.png` (or `_rgba.png` if you want baked colour) to the prototype to see the result.

## Notes

- The generator intentionally bakes lighting into the diffuse map for quick preview. The live GPU renderer uses only the normal + mask and applies its own lighting, so the diffuse map can be ignored there.
- Colour arguments are given as comma-separated `R,G,B` integers in `[0, 255]`.
- The texture is designed to tile in the **U direction** (along the stitch) and clamp in the **V direction** (across the thread).
