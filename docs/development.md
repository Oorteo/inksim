# Developer Guide

## Environment

InkSim uses `uv` and a project-local `.venv`. Synchronize the environment with:

```bash
uv sync --dev
```

The runtime dependencies are declared in `pyproject.toml`. Test tools are in
the `dev` dependency group and are not included in the application wheel.

## Tests

Run the complete test suite from the project root:

```bash
./scripts/040_run_tests.sh
```

The script asks for confirmation before running. Use `-y` or `--yes` for an
unattended run:

```bash
./scripts/040_run_tests.sh --yes
./scripts/040_run_tests.sh --yes -k export
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

1. Run `./scripts/040_run_tests.sh`.
2. Run `git diff --check`.
3. Review the complete diff and confirm that unrelated files are unchanged.
4. Keep runtime dependencies separate from the `dev` dependency group.
