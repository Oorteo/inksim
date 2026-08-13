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

The idea behind this tool dates back to 2013 with an experimental C++/Qt project
called Orca, which originally explored graph algorithms for Inkscape on Linux
before turning into a digitizer and stitch viewer. Here is an old recording of
that early prototype in action:

[Orca viewer demo](https://www.youtube.com/watch?v=VKle5ApsMnA)

**InkSim** is a fresh, standalone rewrite of that viewer concept -- built from
scratch using Python, PySide6, and Numba. The main goal is to provide a fast,
lightweight way to preview embroidery files without heavy overhead.

It was built to fill a small workflow gap, and it's shared with the hope that
others in the Inkscape and Ink/Stitch community might find it helpful as well.

Special thanks to the Ink/Stitch team and community for keeping open-source
embroidery alive and inspiring.

## License

InkSim is released under the [GNU General Public License v3 or later](LICENSE).
