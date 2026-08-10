# InkSim

InkSim is a standalone interactive embroidery simulator and preview renderer.
It opens embroidery files, displays their stitch sequence, and lets the user
inspect or replay the design before production. It is implemented as a small
Python/PySide6/Numba application with its own standalone user interface.

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
inksim design.pes
```

See [installation and running](docs/installation.md) for `pip`/virtual-environment
installation and developer setup.

## Quick start

```bash
inksim
inksim design.pes
inksim design.pes --play
```

## Documentation

- [Project overview](docs/index.md)
- [Installation and running](docs/installation.md)
- [User guide](docs/user-guide.md)
- [Contributing](CONTRIBUTING.md)

## Background

I started working on embroidery tooling in 2013 with a small project called Orca.
It began as a C++/Qt experiment with graph algorithms for Inkscape on Linux and
later grew into a digitizer and a stitch viewer. An old recording of the viewer is here:

[Orca viewer demo](https://www.youtube.com/watch?v=VKle5ApsMnA)

InkSim is a new, standalone implementation of the same viewer idea, written from scratch in Python, PySide6 and Numba and focused on quickly previewing embroidery files. It's a small viewer I was missing myself, so I kept it as a lightweight tool and I'm sharing it here in case it's useful for others in the Inkscape / Ink/Stitch community.

Thanks to the Ink/Stitch project and its community for keeping this space alive and inspiring.

## License

InkSim is released under the [GNU General Public License v3 or later](LICENSE).
