#!/usr/bin/env python3
"""Create a Windows-friendly ZIP bundle for the pen plotter GUI."""
from __future__ import annotations

import argparse
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "dist" / "PenPlotter-Windows.zip"
INCLUDE_PATHS = [
    ROOT / "plotter_gui.py",
    ROOT / "single_file_plotter.py",
    ROOT / "requirements.txt",
    ROOT / "README.md",
    ROOT / "pen_plotter",
]


def iter_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    files = []
    for child in sorted(path.rglob("*")):
        if child.is_file():
            files.append(child)
    return files


def build_bundle(output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
        for src in INCLUDE_PATHS:
            for file_path in iter_files(src):
                arcname = file_path.relative_to(ROOT)
                zf.write(file_path, arcname.as_posix())
    print(f"Created bundle at {output}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Package the Pen Plotter GUI and dependencies into a ZIP archive."
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Path of the ZIP archive to create (default: dist/PenPlotter-Windows.zip)",
    )
    args = parser.parse_args()
    build_bundle(args.output)


if __name__ == "__main__":
    main()
