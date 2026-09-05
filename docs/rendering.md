# Rendering modes and overlays

InkSim can visualise the same embroidery design in several different ways.
The goal is the same in every mode: show the stitch sequence, thread
colours, and jumps clearly. Some modes are fast, others are more realistic,
and a few are specialised overlays for checking the design before production.

Switch renderers with the **R** key, or pick one from the **File → Renderer**
menu. Toggle overlays with the single-letter shortcuts shown below.

---

## Stitch renderers

### Simple

The fastest renderer. Each stitch is drawn as a thin line. Use it for very
large designs or slow machines.

<p align="center"><img src="assets/rendering/010_simple.webp" alt="Simple renderer" width="400"></p>

### Shaded

A CPU raster renderer that draws stitches with simple directional shading.
Faster than the volume renderers but still gives a sense of thread direction.

<p align="center"><img src="assets/rendering/020_shaded.webp" alt="Shaded renderer" width="400"></p>

### Shaded Volume

The default CPU renderer. Stitches are drawn as small shaded volumes, so the
design looks like a stack of stitches rather than flat lines.

<p align="center"><img src="assets/rendering/030_shaded_volume.webp" alt="Shaded Volume renderer" width="400"></p>

### Shaded Volume Natural

A variant of Shaded Volume with more natural-looking lighting. Good for
screenshots and previews that should look close to real thread.

<p align="center"><img src="assets/rendering/040_shaded_volume_natural.webp" alt="Shaded Volume Natural renderer" width="400"></p>

### Realistic Twist

Adds a twist-like texture to each stitch. Useful when you want to see how the
thread might look under side lighting.

<p align="center"><img src="assets/rendering/050_realistic_twist.webp" alt="Realistic Twist renderer" width="400"></p>

### GPU Textured

The most realistic renderer. Draws each stitch as a normal-mapped ribbon quad
with Blinn-Phong lighting. Requires **OpenGL 3.3**; InkSim falls back to a CPU
renderer automatically if the GPU renderer is not available.

<p align="center"><img src="assets/rendering/060_gpu_textured.webp" alt="GPU Textured renderer" width="400"></p>

---

## Overlays and helpers

Overlays do not change the stitch renderer; they add extra information on top
of it.

| Key   | Overlay          | Purpose                                                        |
| ----- | ---------------- | -------------------------------------------------------------- |
| **X** | Density map      | Highlights areas with too many stitches per square mm          |
| **J** | Jumps            | Shows jump stitches and trims                                  |
| **N** | Needle crosshair | Shows the current needle position and direction                |
| **G** | Measurement grid | Adds a millimetre / centimetre grid behind the design          |
| **E** | Bottom view      | Draws later stitches under earlier ones, as seen from the back |

### Density map

The density map highlights places where stitches are packed too tightly.
Dark red areas should be reviewed before production.

<p align="center"><img src="assets/rendering/070_density_overlay.webp" alt="Density overlay" width="400"></p>

### Jumps

Jump stitches are shown as thin connecting lines. Press **J** repeatedly to
cycle through _off_, _all jumps_, and _risky jumps only_.

<p align="center"><img src="assets/rendering/080_jumps_overlay.webp" alt="Jumps overlay" width="400"></p>

### Needle crosshair

The needle overlay marks the current stitch position with a crosshair and an
outlined circle. It is especially helpful during playback.

<p align="center"><img src="assets/rendering/090_needle_overlay.webp" alt="Needle overlay" width="400"></p>

### Measurement grid

The grid shows millimetre, centimetre, and major 5 cm lines, plus the X and Y
axes. It is drawn behind the stitches and is useful for checking real-world
sizes.

<p align="center"><img src="assets/rendering/110_grid.webp" alt="Measurement grid" width="400"></p>

### Bottom view

Bottom view reverses the draw order so later stitches appear _under_ earlier
ones. It simulates looking at the embroidery from the back side of the fabric.

<p align="center"><img src="assets/rendering/100_bottom_view.webp" alt="Bottom view" width="400"></p>

---

## Tips

- Press **Z** to toggle the GPU textured renderer quickly.
- Press **1** to see the design at its physical size for the current display.
- Use **+** / **−** to zoom in and out.
- Combine renderers and overlays freely: for example, use Shaded Volume with
  the density overlay to review both appearance and stitch density at once.
