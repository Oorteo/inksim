# User Guide

## Mouse and Window

| Action                     | Function                  |
| -------------------------- | ------------------------- |
| Mouse wheel                | Zoom around the cursor    |
| Left-drag in viewer        | Pan the design            |
| Click or drag the timeline | Seek to a stitch position |
| Drop a file on the viewer  | Open the file             |
| `F11`                      | Toggle fullscreen         |

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
| `1`                   | Display at physical 1:1 size when display PPI is available |
| `G`                   | Toggle the 1 cm helper grid                                |
| `V`                   | Toggle embroidery visibility                               |
| `R`                   | Toggle realistic thread rendering and fabric background    |
| `J`                   | Cycle jumps: off, all jumps, risky jumps only              |
| `X`                   | Toggle the stitch-density map                              |
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
The density map is prepared in the background after a design is loaded in the
main viewer and cached until a new design is loaded. The open-dialog preview
does not calculate density while moving between files, and command-line PNG
exports skip the calculation.

## Performance Diagnostics

Density and preview timing diagnostics are disabled by default. Enable them
when investigating slow file changes or rendering. The default log path is
next to the first input file, using its basename with a `.log` suffix. Without
an input file, the default is `inksim.log` in the current directory:

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
