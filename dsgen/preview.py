"""Symbol and footprint preview: kicad-cli exports SVG and PyMuPDF rasterizes it to PNG."""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import pymupdf as fitz

from .kicad_env import KicadInstall

FP_LAYERS = "F.Cu,F.SilkS,F.Fab,F.CrtYd,F.Mask"


def _svg_to_png(svg: Path, png: Path, max_px: int) -> Path:
    doc = fitz.open(svg)
    page = doc[0]
    zoom = max_px / max(page.rect.width, page.rect.height, 1)
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    pix.save(png)
    doc.close()
    return png


def _run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"kicad-cli failed: {r.stdout}{r.stderr}")


def symbol_png(kicad: KicadInstall, lib: Path, symbol: str, png: Path, max_px: int = 520) -> Optional[Path]:
    with tempfile.TemporaryDirectory() as tmp:
        _run([str(kicad.cli), "sym", "export", "svg", str(lib), "-s", symbol, "-o", tmp])
        svgs = sorted(Path(tmp).glob("*.svg"))
        return _svg_to_png(svgs[0], png, max_px) if svgs else None


def footprint_png(kicad: KicadInstall, kicad_mod: Path, png: Path, max_px: int = 520) -> Optional[Path]:
    with tempfile.TemporaryDirectory() as tmp:
        _run([str(kicad.cli), "fp", "export", "svg", str(kicad_mod.parent), "--fp", kicad_mod.stem,
              "-l", FP_LAYERS, "--sp", "-o", tmp])
        svgs = sorted(Path(tmp).glob("*.svg"))
        return _svg_to_png(svgs[0], png, max_px) if svgs else None
