# Developer Guide

## Contents

- [Environment](#environment)
- [Development Workflow](#development-workflow)
  - [Linting and formatting](#linting-and-formatting)
  - [Type checking](#type-checking)
  - [Tests](#tests)
  - [Pre-commit hooks](#pre-commit-hooks)
- [Internationalization (i18n)](#internationalization-i18n)
  - [Fallback chain](#fallback-chain)
  - [Adding or changing a UI string](#adding-or-changing-a-ui-string)
  - [Translating locales via Ollama](#translating-locales-via-ollama)
  - [Running the application in another language](#running-the-application-in-another-language)
- [Rendering Architecture](#rendering-architecture)
- [Runtime Diagnostics](#runtime-diagnostics)
- [Test Data](#test-data)
- [Packaging Check](#packaging-check)
- [Code Changes](#code-changes)

## Environment

InkSim uses `uv` and a project-local `.venv`. Synchronize the environment with:

```bash
uv sync --dev
```

The runtime dependencies are declared in `pyproject.toml`. Test tools are in
the `dev` dependency group and are not included in the application wheel.

### `uv run` vs `uvr`

The documentation uses `uv run` because it is available to everyone who has
`uv` installed. Some project scripts use a `uvr` shebang instead — `uvr` is a
small helper that wraps `uv run` and is installed separately with
`uv tool install uvr`. It is optional: every `uvr <command>` in the scripts is
equivalent to `uv run <command>`, so you can run the same scripts with `uv run`
if you do not have `uvr` installed.

## Development Workflow

InkSim ships with a small interactive task menu in the project root:

```bash
./run.py
```

The menu uses numbers so there is no risk of typos. The most common quick
checks are first, the slow test suite is on `0`, and one-off setup tasks are
at the end:

```text
1: lint + typecheck      -> uv run poe check
2: run linter            -> uv run poe lint
3: run type checker      -> uv run poe typecheck
4: preview format changes -> uv run ruff format . --diff
5: format source files   -> uv run poe format
6: preview auto-fixes    -> uv run ruff check . --diff
7: auto-fix lint issues  -> uv run poe fix
8: install git hooks     -> uv run poe install-hooks
9: install dev env       -> uv sync --all-groups
0: run tests             -> uv run poe test
q: quit
```

You can also run tasks directly with `uv run poe <task>`. Available tasks are
`test`, `lint`, `format`, `typecheck`, `fix`, `check` and `install-hooks`.

### Linting and formatting

`ruff` handles linting, import sorting and formatting. The configuration lives
in `pyproject.toml`. Run it before a commit:

```bash
uv run poe fix     # auto-fix what is safe
uv run poe format  # apply formatting
uv run poe check   # lint + mypy
```

### Type checking

`mypy` is configured in `pyproject.toml`. Run it with:

```bash
uv run poe typecheck
```

The project supports Python 3.11+ at runtime, but `mypy` is configured to parse
with Python 3.12 syntax so that current third-party stubs keep working.

### Tests

The test suite runs with `pytest` and `pytest-cov`:

```bash
uv run poe test
```

It produces a terminal coverage summary and an HTML report in `htmlcov/`.

### Pre-commit hooks

Git hooks are optional but recommended. Install them once with:

```bash
uv run poe install-hooks
```

## Internationalization (i18n)

InkSim uses message-ID based JSON catalogs under `src/inksim/locales/`. Each
locale is a flat JSON object where keys are stable IDs and values contain a
`source` string (English source-of-truth) and a `translation` string.

Supported locales are discovered automatically from files in that directory.
Locale tags follow [BCP 47](https://tools.ietf.org/html/bcp47) with a hyphen,
for example `pt-BR`, `pt-PT` or `cs-CZ`.

### Fallback chain

When a string is missing in a specific locale, the runtime falls back through:

1. the exact locale file (e.g. `pt-BR.json`)
2. the base language file (e.g. `pt.json`)
3. the English source catalog (`en.json`)

This lets regional variants contain only the strings that differ from the base
language.

### Adding or changing a UI string

1. Use the imported `_` helper in source code:

   ```python
   from ..i18n import _

   button = QPushButton(_("status.slider.width"))
   ```

2. Run the extractor to update the English catalog:

   ```bash
   uv run python scripts/i18n/extract.py
   ```

   This scans the source for `_()` calls, adds new IDs to `en.json` with the
   source text, and preserves existing translations in the other locale files.

### Translating locales via Ollama

The translator sends only **missing or stale** strings to a local Ollama model,
so repeated runs are cheap:

```bash
# Translate a single locale
uv run python scripts/i18n/translate.py --lang cs --model deepseek-v4-flash:cloud

# Regional variant, e.g. Brazilian Portuguese
uv run python scripts/i18n/translate.py --lang pt-BR --model deepseek-v4-flash:cloud

# Translate every roadmap locale up to a tier
uv run python scripts/i18n/manage.py translate-all --tier 2 --model deepseek-v4-flash:cloud
```

The script accepts both `pt-BR` and `pt_BR.UTF-8` style tags. Use `--dry-run`
to preview the prompt without calling the model.

### Running the application in another language

```bash
uv run python -m inksim --lang cs
uv run python -m inksim -l sk
```

The chosen locale is persisted in the config file, so omitting `--lang` uses
the last selected one.

The application also respects the system locale variables:

```bash
LANG=pt_BR.UTF-8 uv run python -m inksim
LANGUAGE=cs:sk:de uv run python -m inksim
```

Resolution order is: CLI argument → config → `LANGUAGE` (colon-separated
priority list) → `LC_ALL` → `LANG` → `en`. Each locale also falls back to its
base language (e.g. `pt-BR` → `pt`) before the next priority entry is tried.
GitHub issues or pull requests; the JSON format is self-contained and diffs
well.

Before each commit the hooks run a quick `ruff check`, `ruff format --check`
and `mypy`. The full test suite is intentionally not in the hook so commits
stay fast.

## Rendering Architecture

The current viewer intentionally uses a portable CPU rendering path:

```text
Numba/NumPy raster buffer -> QImage -> Qt QPainter/QPixmap
```

The raster renderers (`shaded`, `shaded_volume`, `realistic_twist`, and
related modes) calculate pixels in Numba on the CPU. The `simple` renderer
draws with Qt's regular raster `QPainter`. The `gpu_textured` renderer
rasterizes textured thread quads via OpenGL. The viewer does not use
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
