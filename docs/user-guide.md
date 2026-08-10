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
uv run inksim design.pes --simple-png output.png
uv run inksim design.pes --png shaded-output.png
uv run inksim design.pes --icon preview.png
```

| Option                    | Description                                 |
| ------------------------- | ------------------------------------------- |
| `--simple-png PATH`       | Flat PNG at the design's physical size      |
| `--png PATH`              | Shaded PNG at the design's physical size    |
| `--icon PATH`             | 256 x 256 transparent preview               |
| `--dpi N`                 | DPI for print-sized exports; default is 300 |
| `--bg transparent\|white` | Select the export background                |
| `--grid`                  | Add a 10 mm grid to the exported image      |

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
The density map is calculated lazily when enabled and cached until a new design
is loaded.
