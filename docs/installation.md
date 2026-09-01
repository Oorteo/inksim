# Installation and Running

The recommended end-user installation uses the published `inksim` package
from PyPI. Install [uv](https://docs.astral.sh/uv/getting-started/installation/)
first.

## Windows and macOS

Install the command-line application into uv's tool environment:

```bash
uv tool install inksim
```

The command is then available as `inksim`:

```bash
inksim design.pes
```

If the command is not found, let `uv` add its tool directory to the shell
`PATH` and restart the shell:

```bash
uv tool update-shell
```

## Linux

PySide6-Essentials is installed from PyPI together with InkSim, so no
distribution-specific GUI wheel index is required.

## Alternative: pip and venv

`uv` is not required. Create a virtual environment with Python 3.12 or newer
and install the package with `pip`:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install inksim
inksim design.pes
```

The activation command differs on Windows:

```powershell
.venv\Scripts\Activate.ps1
```

## Developer installation

Clone the repository and synchronize its development environment:

```bash
git clone https://github.com/oorteo/inksim.git
cd inksim
uv sync
```

Run the checked-out version with:

```bash
uv run inksim
uv run inksim design.pes
```

The repository also contains a setup helper. It can recreate `.venv` on macOS,
Linux, and Windows when run from Git Bash or WSL:

```bash
./scripts/dev/010_setup_uv_venv.sh
```

## Command-line and GUI modes

InkSim can be used in two ways:

- As a **GUI application** — the `inksim` command opens the graphical window
  and does not create a terminal window on Windows.
- From an **already open terminal** — the `inksim-cli` command runs with the
  console attached, so output, log messages, and errors are visible in that
  terminal. Behavior is otherwise identical to `inksim`.

On Windows only `inksim-cli` keeps a console window open; `inksim` itself is a
GUI entry point that does not spawn a terminal when started from a shortcut,
file association, or `Win+R`.

## Running options

Start playback, fullscreen mode, or an explicitly sized window with:

```bash
inksim design.pes --play
inksim design.pes --fullscreen
inksim design.pes --size 1600x1000 --position 100,50
```

Pass a directory, including `.`, to open the file dialog in that directory:

```bash
inksim .
```

All the same options work with `inksim-cli` when run from a terminal.
