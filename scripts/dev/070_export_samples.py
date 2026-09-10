#!/usr/bin/env uvr
# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Export all sample embroidery files into the project log directory.

This script renders every embroidery file under ``tests/data`` (recursively)
in several export variants so the visual output can be inspected quickly.

Usage:

    uvr python scripts/dev/070_export_samples.py

Output layout under ``log/export/``:

    simple/     --flat, print-friendly PNG (``--simple-png``)
    shaded/     --default shaded PNG (``--png``)
    webp/       --shaded WebP (``--webp``)
    icon/       256x256 preview PNG (``--icon``)
    grid/       shaded PNG with measurement grid (``--png --grid``)
    white/      shaded PNG on white background (``--png --bg white``)
    white_grid/ shaded PNG on white background with grid

Each output name includes the input extension so ``sample.csv`` and
``sample.pes`` do not collide, e.g. ``sample_csv.png`` and ``sample_pes.png``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "tests" / "data"
OUTPUT_ROOT = PROJECT_ROOT / "log" / "export"
SUPPORTED_EXTENSIONS = {".pes", ".dst", ".csv", ".exp", ".jef", ".vp3"}


def find_embroidery_files(root: Path) -> list[Path]:
    """Return all embroidery files under *root*, sorted."""
    files: list[Path] = []
    if root.is_dir():
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
                files.append(path)
    elif root.is_file() and root.suffix.lower() in SUPPORTED_EXTENSIONS:
        files.append(root)
    files.sort()
    return files


def _input_type_tag(input_path: Path) -> str:
    """Return a safe tag such as ``_pes`` or ``_csv`` based on the input extension."""
    ext = input_path.suffix.lstrip(".").lower()
    return f"_{ext}" if ext else ""


def run_export(input_path: Path, output_dir: Path, options: list[str]) -> Path:
    """Run ``inksim`` for a single export variant and return the output path.

    *options* are extra CLI flags such as ``--grid`` or ``--bg white``.  The
    first option is the export mode (``--simple-png``, ``--png``, ``--webp`` or
    ``--icon``) and is combined with the output file as ``--mode=PATH`` so
    argparse does not confuse the path with an additional input file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    export_mode = options[0]
    type_tag = _input_type_tag(input_path)
    suffix = {
        "--simple-png": f"{type_tag}-simple.png",
        "--png": f"{type_tag}.png",
        "--webp": f"{type_tag}.webp",
        "--icon": f"{type_tag}_thumb.png",
    }[export_mode]
    output_file = output_dir / f"{input_path.stem}{suffix}"
    mode_arg = f"{export_mode}={output_file}"
    cmd = [
        sys.executable,
        "-m",
        "inksim",
        str(input_path),
        mode_arg,
        *options[1:],
        "-y",
    ]
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    result = subprocess.run(cmd, cwd=PROJECT_ROOT, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"FAIL {input_path.name} {' '.join(options)}:\n{result.stderr}", file=sys.stderr)
        raise SystemExit(result.returncode)
    if not output_file.is_file():
        print(f"MISSING {output_file}", file=sys.stderr)
        raise SystemExit(1)
    return output_file


def export_variants(input_path: Path) -> dict[str, Path]:
    """Render all desired variants for *input_path* and return a name->path map."""
    return {
        "simple": run_export(input_path, OUTPUT_ROOT / "simple", ["--simple-png"]),
        "shaded": run_export(input_path, OUTPUT_ROOT / "shaded", ["--png"]),
        "webp": run_export(input_path, OUTPUT_ROOT / "webp", ["--webp"]),
        "icon": run_export(input_path, OUTPUT_ROOT / "icon", ["--icon"]),
        "grid": run_export(input_path, OUTPUT_ROOT / "grid", ["--png", "--grid"]),
        "white": run_export(input_path, OUTPUT_ROOT / "white", ["--png", "--bg", "white"]),
        "white_grid": run_export(
            input_path, OUTPUT_ROOT / "white_grid", ["--png", "--bg", "white", "--grid"]
        ),
    }


def main() -> int:
    if shutil.which(sys.executable) is None:
        print("cannot locate python interpreter", file=sys.stderr)
        return 1

    if not DATA_DIR.exists():
        print(f"sample data directory not found: {DATA_DIR}", file=sys.stderr)
        return 1

    files = find_embroidery_files(DATA_DIR)
    if not files:
        print(f"no embroidery files found under {DATA_DIR}", file=sys.stderr)
        return 1

    print(f"Exporting {len(files)} sample file(s) to {OUTPUT_ROOT}")
    for embroidery_file in files:
        print(f"  {embroidery_file.relative_to(PROJECT_ROOT)}")
        paths = export_variants(embroidery_file)
        for variant, path in paths.items():
            print(f"    {variant}: {path.relative_to(PROJECT_ROOT)}")

    print(f"\nDone. Inspect the results under {OUTPUT_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
