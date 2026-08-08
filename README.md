# InkSim

InkSim is a standalone interactive embroidery simulator and preview renderer.
It opens embroidery files, displays their stitch sequence, and lets the user
inspect or replay the design before production. It is implemented as a small
Python/wxPython/Numba application with its own standalone user interface.

<p align="center">
  <img src="docs/assets/images/InkSim_colorful_small.png" alt="InkSim preview" width="350">
</p>

InkSim is experimental software provided for development and testing.

## Installation

Install the published PyPI package with `uv`:

```bash
uv tool install inksim
```

Then run it directly from your shell:

```bash
inksim design.dst
```

Linux users need a wxPython wheel matching their distribution. For example,
Ubuntu 24.04 users can install InkSim with:

```bash
uv tool install --find-links https://extras.wxpython.org/wxPython4/extras/linux/gtk3/ubuntu-24.04 inksim
```

See [installation and running](docs/installation.md) for other Linux
versions, `pip`/virtual-environment installation, and developer setup.

## Quick start

```bash
inksim
inksim design.dst
inksim design.dst --play
```

## Documentation

- [Project overview](docs/index.md)
- [Installation and running](docs/installation.md)
- [User guide](docs/user-guide.md)
- [Contributing](CONTRIBUTING.md)

## License

InkSim is released under the [GNU General Public License v3 or later](LICENSE).
