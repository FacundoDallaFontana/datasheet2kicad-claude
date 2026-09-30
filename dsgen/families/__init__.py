"""Traducción de `Package` a cada generador de footprint.

Cada familia expone `build(pkg, out_dir) -> Path` que escribe un único .kicad_mod en
`out_dir` (carpeta temporal) y devuelve su ruta.
"""
from __future__ import annotations

import os
from argparse import Namespace
from pathlib import Path

from ..schema import Dim

_initialized_for: Path | None = None


def init_kfg(out_dir: Path) -> None:
    """Inicializa el estado global de kicad-footprint-generator.

    Debe llamarse antes de importar `generators.package.*` (leen CLI_ARGS al importarse).
    """
    global _initialized_for
    import generators
    from generators.tools import cli_args

    if _initialized_for is not None:
        # Los módulos del generador hacen `from cli_args import CLI_ARGS`: hay que mutar
        # ese mismo objeto, no reemplazarlo.
        cli_args.CLI_ARGS.output_dir_footprints = out_dir
        _initialized_for = out_dir
        return
    os.environ.setdefault("GENERATORS", Path(list(generators.__path__)[0]).as_posix())
    cli_args.init(Namespace(
        package_config="${GENERATORS}/package/package_config_KLCv3.yaml",
        output_dir_footprints=out_dir, output_dir_models=None,
        separate_outputs=False, dry_run=False,
    ))
    _initialized_for = out_dir


def tol(d: Dim) -> dict:
    """Dim -> formato TolerancedSize de los YAML de kicad-footprint-generator."""
    out = {}
    if d.min is not None:
        out["minimum"] = d.min
    if d.nom is not None:
        out["nominal"] = d.nom
    if d.max is not None:
        out["maximum"] = d.max
    return out


def device_type(pkg_name: str, fallback: str) -> str:
    """'VQFN-16 (RGT)' -> 'VQFN', 'SO-8' -> 'SOIC'."""
    token = pkg_name.strip().split()[0] if pkg_name.strip() else fallback
    token = token.split("-")[0].upper()
    token = "".join(ch for ch in token if ch.isalnum())
    return {"SO": "SOIC", "SOP": "SOIC"}.get(token, token or fallback)


def single_output(out_dir: Path) -> Path:
    files = list(out_dir.rglob("*.kicad_mod"))
    if len(files) != 1:
        raise RuntimeError(f"Se esperaba un footprint generado y hay {len(files)} en {out_dir}")
    return files[0]
