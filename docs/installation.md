# Installation and Running

## Contents

- [Quick start](#quick-start)
- [Update](#update)
- [Alternative installers](#alternative-installers)
- [Developer install](#developer-install)
- [Command-line and GUI modes](#command-line-and-gui-modes)
- [Running options](#running-options)
- [GPU textured renderer](#gpu-textured-renderer)

InkSim is a **standalone GUI application**, not an Inkscape extension. You do
not copy files into Inkscape's `extensions` folder.

> **Ink/Stitch integration** is still in PR review. Until it is merged, export
> the embroidery as CSV from Ink/Stitch and open that file in InkSim.

## Quick start

1. Install [`uv`](https://docs.astral.sh/uv/getting-started/installation/):
   - **macOS / Linux:**

     ```bash
     curl -LsSf https://astral.sh/uv/install.sh | sh
     ```

   - **Windows (PowerShell):**

     ```powershell
     powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
     ```

   Restart the terminal so `uv` is on `PATH`.

2. Install InkSim:

   ```bash
   uv tool install inksim
   ```

3. Run it:

   ```bash
   inksim
   inksim design.pes
   ```

On Windows, `inksim-gui design.pes` starts without a console window.

## Update

For an installation made with `uv`, update from PyPI with:

```bash
uv tool upgrade inksim
```

uv prefers stable releases by default. If `0.5.6` is the latest stable version
and `0.6.0rc1` is available as a pre-release, `uv tool upgrade inksim` keeps
users on the stable release unless they explicitly opt in to pre-releases.

In the GUI, **Help → Check for updates** checks the newest stable version on
PyPI and reports whether an update is available; it does not install anything.
It also checks automatically once per day by default. InkSim release
candidates are published on GitHub, not PyPI, and are not offered by this
regular update check. Install a candidate directly from its GitHub release page
if you want to test it. Once the matching final release is published (e.g.
`0.6.0` after `0.6.0rc1`), the update check offers it.

## Alternative installers

`uv` is not required. Any of these work:

```bash
# pip + venv
python -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\Activate.ps1
python -m pip install inksim

# pipx
pipx install inksim

# Poetry
poetry add inksim

# Conda
conda create -n inksim python=3.11
conda activate inksim
pip install inksim
```

## Developer install

```bash
git clone https://github.com/oorteo/inksim.git
cd inksim
uv sync
uv run inksim design.pes
```

## Command-line and GUI modes

- `inksim` — console launcher; keeps output in the terminal.
- `inksim-gui` — GUI launcher.

Both commands exist on Windows, macOS, and Linux. On Linux and macOS they are
identical. Only on Windows do they differ: `inksim-gui` is a GUI-subsystem
executable (a legacy of Windows' DOS heritage) that starts without a console
window, while `inksim` opens one. Use `inksim-gui` on Windows for shortcuts,
file associations, and `Win+R`.

## Running options

```bash
inksim design.pes --play
inksim design.pes --fullscreen
inksim design.pes --size 1600x1000 --position 100,50
inksim .                        # open the file dialog in this directory
```

## GPU textured renderer

The GPU renderer (`Z`) requires **OpenGL 3.3**. On systems without OpenGL 3.3 —
including virtual machines without 3D acceleration — InkSim falls back to the
CPU renderer automatically.
