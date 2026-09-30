"""Detección de la instalación de KiCad y compatibilidad de formato de archivos.

kicad-footprint-generator ya serializa en formato KiCad 10; si la instalación es más vieja
bajamos la versión del archivo y quitamos los tokens que no entiende.
"""
from __future__ import annotations

import functools
import json
import os
import re
import string
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

CONFIG_FILE = Path.home() / ".dsgen" / "config.json"

# Versión de formato .kicad_mod por versión mayor de KiCad.
FP_FORMAT_VERSION = {8: "20240108", 9: "20241229"}
# Tokens de footprint que solo existen desde KiCad 10 (se eliminan líneas completas).
V10_ONLY_FP_TOKENS = ("duplicate_pad_numbers_are_jumpers", "jumper_pad_groups")


@dataclass(frozen=True)
class KicadInstall:
    root: Path
    cli: Path
    version: str  # "9.0.6"

    @property
    def major(self) -> int:
        return int(self.version.split(".")[0])

    @property
    def footprint_dir(self) -> Path:
        return self.root / "share" / "kicad" / "footprints"


def _cli_in(root: Path) -> Optional[Path]:
    for name in ("kicad-cli.exe", "kicad-cli"):
        cli = root / "bin" / name
        if cli.exists():
            return cli
    return None


def _candidate_roots() -> list[Path]:
    roots: list[Path] = []
    if CONFIG_FILE.exists():
        try:
            if (d := json.loads(CONFIG_FILE.read_text(encoding="utf-8")).get("kicad_dir")):
                roots.append(Path(d))
        except (ValueError, OSError):
            pass
    if (d := os.environ.get("DSGEN_KICAD_DIR")):
        roots.append(Path(d))
    if os.name == "nt":
        drives = [Path(f"{c}:/") for c in string.ascii_uppercase[2:8] if Path(f"{c}:/").exists()]
        for drive in drives:
            for parent in (drive / "Program Files" / "KiCad", drive / "KiCad", drive):
                if parent.is_dir():
                    roots += [p for p in parent.iterdir() if p.is_dir() and re.match(r"(kicad)?\d+(\.\d+)?$", p.name, re.I)]
    else:
        roots += [Path("/usr"), Path("/usr/local"),
                  Path("/Applications/KiCad/KiCad.app/Contents/MacOS")]
    return roots


def _version(cli: Path) -> str:
    try:
        out = subprocess.run([str(cli), "version"], capture_output=True, text=True, timeout=30).stdout
        m = re.search(r"\d+\.\d+(\.\d+)?", out)
        return m.group(0) if m else "0.0"
    except (OSError, subprocess.SubprocessError):
        return "0.0"


@functools.lru_cache(maxsize=1)
def find_kicad() -> Optional[KicadInstall]:
    """Devuelve la instalación de KiCad más nueva encontrada, o None."""
    found = []
    for root in _candidate_roots():
        if (cli := _cli_in(root)):
            found.append(KicadInstall(root=root, cli=cli, version=_version(cli)))
    if not found:
        return None
    return max(found, key=lambda k: tuple(int(x) for x in k.version.split(".")))


def save_kicad_dir(root: Path) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    cfg = {}
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except ValueError:
            pass
    cfg["kicad_dir"] = str(root)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    find_kicad.cache_clear()


def downgrade_footprint(path: Path, kicad_major: int) -> None:
    """Adapta un .kicad_mod en formato KiCad 10 a una versión anterior (in-place)."""
    if kicad_major >= 10 or kicad_major not in FP_FORMAT_VERSION:
        return
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"\(version \d+\)", f"(version {FP_FORMAT_VERSION[kicad_major]})", text, count=1)
    lines = [ln for ln in text.splitlines(keepends=True)
             if not any(f"({tok}" in ln for tok in V10_ONLY_FP_TOKENS)]
    path.write_text("".join(lines), encoding="utf-8")
