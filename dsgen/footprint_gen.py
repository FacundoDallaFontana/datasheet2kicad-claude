"""component.package -> footprint (oficial de KiCad si existe uno equivalente, si no generado)."""
from __future__ import annotations

import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .kicad_env import KicadInstall, downgrade_footprint
from .kicad_lib import LibMatch, find_match
from .schema import Package


class UnsupportedPackage(Exception):
    pass


@dataclass
class FootprintResult:
    lib_id: str                          # valor de la propiedad Footprint del símbolo
    generated_path: Optional[Path]       # None si se usa el footprint oficial
    match: Optional[LibMatch]            # candidato oficial más cercano (aceptado o no)
    pin_renames: dict[str, str] = field(default_factory=dict)  # a aplicar a los pines del símbolo


def _builder(family: str):
    if family == "gullwing":
        from .families import gullwing
        return gullwing.build
    if family == "nolead":
        from .families import nolead
        return nolead.build
    if family == "tab":
        from .families import tab
        return tab.build
    raise UnsupportedPackage(f"Familia '{family}' sin generador de footprint.")


def _renumber(text: str, old: str, new: str) -> str:
    return re.sub(rf'\(pad "{re.escape(old)}"', f'(pad "{new}"', text)


def generate_footprint(pkg: Package, lib_name: str, out_dir: Path,
                       kicad: Optional[KicadInstall], use_official: bool = True) -> FootprintResult:
    build = _builder(pkg.family)
    with tempfile.TemporaryDirectory() as tmp:
        path = build(pkg, Path(tmp))
        text = path.read_text(encoding="utf-8")
        name = path.stem

    klc_ep = str(pkg.pin_count + 1)
    match = find_match(text, kicad, pkg.family, name) if kicad else None
    if match and match.accepted and use_official:
        renames = {pkg.ep.number: klc_ep} if pkg.ep and pkg.ep.number != klc_ep else {}
        return FootprintResult(match.lib_id, None, match, renames)

    if pkg.ep and pkg.ep.number != klc_ep and pkg.family != "tab":
        text = _renumber(text, klc_ep, pkg.ep.number)
    pretty = out_dir / f"{lib_name}.pretty"
    pretty.mkdir(parents=True, exist_ok=True)
    dest = pretty / f"{name}.kicad_mod"
    dest.write_text(text, encoding="utf-8")
    if kicad:
        downgrade_footprint(dest, kicad.major)
    return FootprintResult(f"{lib_name}:{name}", dest, match)


def copy_official(lib_id: str, kicad: KicadInstall, dest_dir: Path) -> Path:
    """Copia un footprint oficial (para el preview)."""
    lib, name = lib_id.split(":", 1)
    src = kicad.footprint_dir / f"{lib}.pretty" / f"{name}.kicad_mod"
    dest_dir.mkdir(parents=True, exist_ok=True)
    return Path(shutil.copy(src, dest_dir / src.name))
