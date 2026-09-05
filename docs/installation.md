# Installation and Running

The recommended end-user installation uses the published `inksim` package
from PyPI. Install [uv](https://docs.astral.sh/uv/getting-started/installation/)
first.

## Windows and macOS

Install the command-line application into uv's tool environment:

```bash
uv tool install inksim
```

The console and GUI commands are then available as `inksim` and `inksim-gui`:

```bash
inksim design.pes
inksim-gui design.pes
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

`uv` is not required. Create a virtual environment with Python 3.11 or newer
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

## With pipx

If you already use [pipx](https://pypa.github.io/pipx/) for command-line
Python tools, install InkSim globally into its isolated environment:

```bash
pipx install inksim
inksim design.pes
```

## With Poetry

If your project is managed with [Poetry](https://python-poetry.org/), add
InkSim as a dependency:

```bash
poetry add inksim
poetry run inksim design.pes
```

To install into the current Poetry environment only:

```bash
poetry add --group dev inksim
```

## With Conda

If you use [Conda](https://conda.io/) or [Miniforge](https://conda-for.org/miniforge/),
create an environment with Python 3.11 or newer and install from PyPI:

```bash
conda create -n inksim python=3.11
conda activate inksim
pip install inksim
inksim design.pes
```

InkSim is not yet packaged on `conda-forge`, so the last step uses `pip`
inside the Conda environment.

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

- From an **already open terminal** — the `inksim` command keeps output and
  errors in that terminal. With no export option it opens the graphical window.
- As a **GUI application** — the `inksim-gui` command opens the same graphical
  application without a console window.

These command names and roles are the same on Windows, macOS, and Linux. On
Windows, use `inksim-gui` for shortcuts, file associations, and `Win+R` so no
console window is created.

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

The same GUI options work with `inksim-gui`; terminal output is intentionally
available through `inksim`.

## GPU textured renderer and OpenGL

The _GPU Textured_ stitch renderer (`Z` shortcut or **GPU textured render**
in the File menu) requires **OpenGL 3.3** with a Core Profile context. It is
used automatically only when OpenGL 3.3 is available.

On systems with only OpenGL 3.0 or older — common in virtual machines that do
not expose 3D acceleration, such as a default VirtualBox configuration —
InkSim falls back to the CPU-based _Shaded Volume_ raster renderer. The
fallback happens automatically on startup and when the GPU renderer is
selected, so the application remains usable; only the GPU renderer is
unavailable.
