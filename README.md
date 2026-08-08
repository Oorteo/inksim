# InkSim

InkSim is a standalone interactive embroidery simulator and preview renderer.
It opens embroidery files, displays their stitch sequence, and lets the user
inspect or replay the design before production. It is implemented as a small
Python/wxPython/Numba application with its own standalone user interface.

<p align="center">
  <img src="docs/assets/images/InkSim_colorful_small.png" alt="InkSim preview" width="350">
</p>

InkSim is experimental software provided for development and testing.

## Quick start

```bash
uv sync
uv run inksim
```

Open a design with `uv run inksim design.dst`.

## Documentation

- [Project overview](docs/index.md)
- [Installation and running](docs/installation.md)
- [User guide](docs/user-guide.md)
- [Contributing](CONTRIBUTING.md)

Only one export option may be used at a time. Export mode creates a wx
application without entering the interactive main loop, renders the design,
writes PNG metadata, and exits with status 0 on success.

The PNG metadata includes design dimensions, background, layer type, rendering
mode, and DPI where applicable. The interactive fabric/realistic viewport
renderer is intentionally separate from the current standalone export
renderer.

## Performance Notes

- Numba compiles each kernel on its first use; the first render can therefore
  take longer than subsequent renders.
- The viewer caches the rendered bitmap and uses a temporary stretched bitmap
  while zooming, then schedules a full-quality render after zooming settles.
- Pan operations can reuse the cached bitmap without rerendering the stitches.
- The realistic renderer is more expensive than the normal path because it
  evaluates a pixel footprint around every visible stitch and includes a
  separate shadow pass.
- Maximum thread width and maximum sampling steps are bounded to prevent a
  single long stitch from consuming excessive CPU time.

## Design Boundaries and Future Work

InkSim is a preview and inspection tool, not a stitch optimizer or machine
driver. It does not alter the source design during loading and it does not
replace production-specific checks performed in an embroidery production
workflow.

Likely future rendering improvements include:

- continuous satin-surface or normal-map shading;
- better handling of stitch overlap and needle-hole depressions;
- adaptive supersampling for very dense designs;
- optional texture quality controls;
- a shared export/rendering pipeline when visual parity is required.

## Development Checks

Run the syntax check with the project environment:

```bash
python3 -m py_compile src/inksim/inksim.py
```

Check the patch for whitespace errors:

```bash
git diff --check -- src/inksim/inksim.py README.md
```

## License

InkSim is released under the [GNU General Public License v3 or later](LICENSE).
