# Installation and Running

InkSim uses `pyproject.toml` and `uv.lock` for dependency management. Install
[uv](https://docs.astral.sh/uv/getting-started/installation/) first.

## Linux

On supported Linux distributions, set up the environment with:

```bash
./scripts/setup_linux.sh
```

Use `-y` for a clean, non-interactive setup that removes and recreates the
project `.venv`:

```bash
./scripts/setup_linux.sh -y
```

The setup script is Linux-only and selects a matching wxPython package source.

## Windows and macOS

Create or update the environment directly from the project files:

```bash
uv sync
```

## Start InkSim

From the repository root:

```bash
uv run inksim
uv run inksim design.dst
```

The repository wrapper `./inksim` is also available. To start playback
immediately, add `--play`:

```bash
uv run inksim design.dst --play
```

For fullscreen or explicit window geometry:

```bash
uv run inksim design.dst --fullscreen
uv run inksim design.dst --size 1600x1000 --position 100,50
```
