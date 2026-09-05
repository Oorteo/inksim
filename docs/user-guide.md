# User Guide

## Mouse and Window

| Action                     | Function                     |
| -------------------------- | ---------------------------- |
| Mouse wheel                | Zoom around the cursor       |
| `Alt` + mouse wheel        | Move one stitch              |
| `Ctrl` + mouse wheel       | Move one stitch              |
| Left-drag in viewer        | Pan the design               |
| Double-click design        | Seek to visible stitch       |
| `W` / `A` / `S` / `D`      | Pan up / left / down / right |
| Click or drag the timeline | Seek to a stitch position    |
| Drop a file on the viewer  | Open the file                |
| `F11`                      | Toggle fullscreen            |

## Playback and Navigation

| Shortcut                     | Function                                                         |
| ---------------------------- | ---------------------------------------------------------------- |
| `Space`                      | Play or pause                                                    |
| `Right` / `Left`             | Move by the configured step; change playback speed while playing |
| `Alt+Right` / `Alt+Left`     | Move one stitch                                                  |
| `Up` / `Down`                | Move by ten configured steps                                     |
| `Home` / `End`               | Move to the first or last stitch                                 |
| `Ctrl+Right` / `Ctrl+Left`   | Move to the next or previous color section                       |
| `Shift+Right` / `Shift+Left` | Move to the next or previous command event                       |
| `Esc`                        | Stop playback                                                    |

The Playback menu provides steps of 1, 10, 50, 100, and 500 stitches.

## View and Analysis

| Shortcut              | Function                                                   |
| --------------------- | ---------------------------------------------------------- |
| `C`                   | Center the design                                          |
| `F`                   | Fit the design to the viewer                               |
| `M`                   | Toggle snap layout / normal view                           |
| `1`                   | Display at physical 1:1 size when display PPI is available |
| `G`                   | Toggle the 1 cm helper grid                                |
| `V`                   | Toggle embroidery visibility                               |
| `Z`                   | Toggle realistic thread rendering and fabric background    |
| `R`                   | Choose a stitch renderer                                   |
| `J`                   | Cycle jumps: off, all jumps, risky jumps only              |
| `X`                   | Toggle the stitch-density map                              |
| `B`                   | Cycle background: configured → black → white → configured  |
| `E`                   | Bottom view (draw later stitches under earlier ones)       |
| `N`                   | Toggle the needle marker                                   |
| `H`                   | Show help                                                  |
| `I`                   | Show current viewer settings                               |
| `+` / `-`             | Increase or decrease thread width                          |
| `[` / `]`             | Adjust dark shading                                        |
| `Shift+[` / `Shift+]` | Adjust light shading                                       |

## PNG Export

InkSim supports three non-interactive export modes:

```bash
uv run inksim design.pes --simple-png
uv run inksim design.pes --png
uv run inksim design.pes --icon

# Or provide an explicit output path
uv run inksim design.pes --simple-png output.png
uv run inksim design.pes --png shaded-output.png
uv run inksim design.pes --icon preview.png

# Batch export; each input gets its own basename-derived PNG
uv run inksim *.pes --png
uv run inksim *.pes --png exports/ -y
```

| Option                    | Description                                          |
| ------------------------- | ---------------------------------------------------- |
| `--simple-png [PATH]`     | Flat PNG; defaults to `INPUT-simple.png`             |
| `--png [PATH]`            | Shaded PNG; defaults to `INPUT.png`                  |
| `--icon [PATH]`           | 256 x 256 preview PNG; defaults to `INPUT_thumb.png` |
| `--dpi N`                 | DPI for print-sized exports; default is 300          |
| `--bg transparent\|white` | Select the export background                         |
| `--grid`                  | Add a 10 mm grid to the exported image               |
| `-y`, `--yes`             | Overwrite existing batch output without asking       |

Exported PNG/WebP/JPEG images always set the standard physical-resolution tags
(pixels per meter, i.e. PNG `pHYs` or JPEG EXIF resolution). This lets Inkscape,
GIMP and other tools import the image at the correct real-world size. A single
human-readable `InkSim` text comment is also stored with the design dimensions,
DPI and renderer for quick reference.

When several input files are supplied, omitting the output path creates one
PNG next to each input. An explicit output path must be an existing directory
and is used as the destination directory for all generated PNGs. Existing
files are never overwritten without confirmation; use `-y` or `--yes` for
unattended batch jobs. Batch exports stay console-only and report progress as
`[n/N]`; the GUI currently opens only the first supplied input.

## Supported Files

InkSim supports all embroidery file formats with a reader reported by
`pystitch.EmbPattern.supported_formats()`. The open dialog builds its file
filter from those formats, so the supported extensions follow the installed
version of the pystitch library rather than a separate hard-coded list.
Thread colors are read from the pattern thread list when available; files
without colors use a deterministic fallback palette. Jumps, color changes,
trims, stops, slow, fast, and end markers are interpreted while loading.

## Rendering Notes

Loaded designs are kept in a NumPy array with one row per stitch segment:

```text
[x1, y1, x2, y2, red, green, blue]
```

Coordinates are converted from pystitch units to millimeters and projected to
screen pixels using `screen = world * zoom + pan`. Numba kernels render the
RGB buffer used by the PySide6 viewer.

The realistic renderer adds a procedural fabric background, cylindrical thread
shading, highlights, shadows, and anti-aliased edges. It is intentionally
approximate and can exaggerate sewing direction or dark gaps in satin areas.

The GPU Textured renderer rasterizes stitches as continuous textured ribbon
quads using a normal-map thread texture and Blinn-Phong lighting, giving a
twisted-thread look with selectable thread textures.
The density map is prepared in the background after a design is loaded in the
main viewer and cached until a new design is loaded. The open-dialog preview
does not calculate density while moving between files, and command-line PNG
exports skip the calculation.

### Density Map

Press `X` to show the stitch-density map. Each stitch endpoint is evaluated
within a 2.5 mm radius:

| Color  | Meaning                                   |
| ------ | ----------------------------------------- |
| Blue   | Normal density, below 3 stitches per mm2  |
| Yellow | Warning density, from 3 stitches per mm2  |
| Red    | Critical density, from 6 stitches per mm2 |

Stitches with zero length are highlighted with a thin red circle. Their
center keeps the density color, so they can be distinguished from high-density
areas. The circles are shown only while the density map is enabled and remain
nearly constant in size as the view is zoomed.

## Performance Diagnostics

Density and preview timing diagnostics are disabled by default. Enable them
when investigating slow file changes or rendering. When run from the project
root, the default log path is `log/inksim.log`. The `log` directory is created
automatically. Outside the project root, the default log path is next to the
first input file, using its basename with a `.log` suffix; without an input
file it is `inksim.log` in the current directory:

```bash
uv run inksim --debug design.pes
uv run inksim --dbg design.pes
uv run inksim design.pes --log diagnostics/run.log
```

`--debug` and `--dbg` are aliases. `--log FILE` implies debug logging and
creates missing parent directories. The same settings can be supplied through
the `INKSIM_DEBUG` and `INKSIM_LOG` environment variables.

The log records file loading, preview painting, and density-worker lifecycle
events, including thread IDs and elapsed times. In the open dialog, entries
with `precompute_density=False` confirm that density is not being calculated
for arrow-key preview navigation. The logger is silent and creates no file
unless debug logging is enabled.
