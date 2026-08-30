# Developer Guide

## Environment

InkSim uses `uv` and a project-local `.venv`. Synchronize the environment with:

```bash
uv sync --dev
```

The runtime dependencies are declared in `pyproject.toml`. Test tools are in
the `dev` dependency group and are not included in the application wheel.

## Rendering Architecture

The current viewer intentionally uses a portable CPU rendering path:

```text
Numba/NumPy raster buffer -> QImage -> Qt QPainter/QPixmap
```

The raster renderers (`shaded`, `shaded_volume`, `realistic`, and related
modes) calculate pixels in Numba on the CPU. The `simple` and `vintage`
renderers draw with Qt's regular raster `QPainter`. The `gpu_textured`
renderer rasterizes textured thread quads via OpenGL. The viewer does not use
`QGraphicsView`, Vulkan, or Qt Quick.

Do not add `QOpenGLWidget` merely as a viewport optimization. It would not
accelerate the existing Numba/NumPy calculations and would add backend and
driver failure modes, especially on older or headless systems. The current
CPU path is the intentional fallback and the baseline for all platforms.

The same renderer registry is used by the GUI and PNG export. `Simple PNG`
explicitly uses the `simple` renderer; the regular GUI export uses the active
renderer. Keep this behavior stable.

The current realistic modes are useful approximations, not a complete
physically based thread renderer. Revisit a GPU backend only after one of
these conditions is met:

1. A full realistic renderer needs effects that are naturally implemented as
   GPU shaders.
2. Profiling shows the CPU renderer is the actual bottleneck on representative
   large designs.
3. A separate GPU backend can be added with a tested CPU fallback.

Until then, optimize measured CPU costs first: render-buffer reuse, cache
invalidations, density recalculation, Numba kernels, and unnecessary image
copies. Do not treat OpenGL availability as a prerequisite for InkSim.

Numba functions use `@numba.njit(cache=True)`. Numba specializes them from
the actual argument types, then stores compiled variants in local `.nbi` and
`.nbc` files under `__pycache__`. This avoids recompiling the same variants on
later runs of the same environment. These cache files are platform-, Python-,
NumPy-, Numba-, and CPU-specific; they are generated after installation and
must not be committed or bundled as universal distribution artifacts.

Do not enable `parallel=True` or `fastmath=True` on the per-stitch renderers
without measuring both performance and visual changes.

## Runtime Diagnostics

Show the installed InkSim version and the runtime used to start it:

```bash
uv run inksim -v
```

The diagnostic output includes the source or installed-package mode, package
location, Python version and executable, active virtual environment, working
directory, PySide6 and Qt versions, NumPy, Numba, and pystitch versions. The
version comes from installed package metadata, so the same command works for
an editable checkout and for a built wheel.

Run the complete test suite from the project root:

```bash
./scripts/dev/040_run_tests.sh
```

The script asks for confirmation before running. Use `-y` or `--yes` for an
unattended run:

```bash
./scripts/dev/040_run_tests.sh --yes
./scripts/dev/040_run_tests.sh --yes -k export
```

The script can also be started from another directory. It runs tests with
verbose names and duration information, prints the output to the terminal, and
writes the latest report to:

```text
log/tests/latest.log
```

The `log/` directory is ignored by Git. A failed test still produces the log
and the script returns pytest's failure status.

Run pytest directly when a custom selection is useful:

```bash
uv run pytest tests -q
uv run pytest tests/test_shortcuts.py -vv
uv run pytest tests -k export
```

The current tests cover renderer smoke tests, Qt keyboard shortcuts, command
events, risky jump grouping, sample loading, and CLI PNG exports. They check
that the application responds correctly and does not crash; they are not pixel
comparison tests.

## Test Data

Small embroidery fixtures live in `tests/data/` and use generic names so they
can be replaced without changing the tests:

```text
tests/data/sample.csv
tests/data/sample.pes
tests/data/square.pes
```

The `sample_design` pytest fixture selects an available sample from this
folder. Test data and the `tests/` directory are excluded from application
wheels.

## Packaging Check

Build a wheel and inspect its contents with:

```bash
uv build --wheel
```

The wheel should contain the application and runtime assets, but not tests,
test fixtures, or pytest dependencies.

## Code Changes

Before submitting a change:

1. Run `./scripts/dev/040_run_tests.sh`.
2. Run `git diff --check`.
3. Review the complete diff and confirm that unrelated files are unchanged.
4. Keep runtime dependencies separate from the `dev` dependency group.
