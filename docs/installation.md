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

The PyPI package does not include a binary wxPython wheel for Linux. Use the
wxPython extras index matching your distribution. For Ubuntu 24.04:

```bash
uv tool install --find-links https://extras.wxpython.org/wxPython4/extras/linux/gtk3/ubuntu-24.04 inksim
```

Other available indexes are listed at the
[wxPython Linux extras](https://extras.wxpython.org/wxPython4/extras/linux/gtk3/)
page. Replace the distribution directory in `--find-links`, for example:

```bash
uv tool install --find-links https://extras.wxpython.org/wxPython4/extras/linux/gtk3/ubuntu-22.04 inksim
```

The available directory must match both the Linux distribution and its
wxPython/Python compatibility. The extras page currently includes Ubuntu,
Debian, Fedora, Rocky, and CentOS directories.

## Alternative: pip and venv

`uv` is not required. Create a virtual environment with Python 3.12 or newer
and install the package with `pip`:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install inksim
inksim design.pes
```

On Linux, pass the matching wxPython extras index to `pip` as well:

```bash
python -m pip install --find-links https://extras.wxpython.org/wxPython4/extras/linux/gtk3/ubuntu-24.04 inksim
```

The activation command differs on Windows:

```powershell
.venv\Scripts\Activate.ps1
```

## Developer installation

Clone the repository and synchronize its development environment:

```bash
git clone https://github.com/karnigen/inksim.git
cd inksim
uv sync
```

Run the checked-out version with:

```bash
uv run inksim
uv run inksim design.pes
```

On Linux, if the required wxPython wheel is not available from the default
package index, use the distribution-specific extras index while syncing:

```bash
uv sync --find-links https://extras.wxpython.org/wxPython4/extras/linux/gtk3/ubuntu-24.04
```

The repository also contains a setup helper. It can recreate `.venv` on macOS,
Linux, and Windows when run from Git Bash or WSL; on supported Linux
distributions it also selects the wxPython source automatically:

```bash
./scripts/setup_uv_venv.sh
```

## Running options

Start playback, fullscreen mode, or an explicitly sized window with:

```bash
inksim design.pes --play
inksim design.pes --fullscreen
inksim design.pes --size 1600x1000 --position 100,50
```
