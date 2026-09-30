"""component.json -> KiPart CSV -> .kicad_sym"""
from __future__ import annotations

import contextlib
import csv
import io
import re
import tempfile
from pathlib import Path

from kipart.kipart import row_file_to_symbol_lib_file

from .schema import Component


HIDDEN_PROPS = ("Manufacturer", "MPN")


def _clean(text: str, allow_comma: bool = False) -> str:
    # KiPart does not accept commas in pin/symbol names, nor line breaks.
    if not allow_comma:
        text = text.replace(",", "/")
    return " ".join(text.split())


def _hide_props(lib_path: Path) -> None:
    """KiPart leaves custom properties visible; hide them as the official library does."""
    text = lib_path.read_text(encoding="utf-8")
    for prop in HIDDEN_PROPS:
        text = re.sub(rf'(\(property "{prop}" (?:(?!\(property ).)*?)\(hide no\)', r"\1(hide yes)",
                      text, flags=re.S)
    lib_path.write_text(text, encoding="utf-8")


def to_kipart_rows(c: Component, footprint: str) -> list[list[str]]:
    rows = [[_clean(c.symbol_name or c.part_number)]]
    props = {
        "Reference": c.reference or "U",
        "Value": c.symbol_name or c.part_number,
        "Footprint": footprint,
        "Datasheet": c.datasheet_url,
        "Description": c.description,
        "Keywords": c.keywords,
        "Manufacturer": c.manufacturer,
        "MPN": c.part_number,
    }
    rows += [[f"{k}:", _clean(v, allow_comma=True)] for k, v in props.items() if v]
    rows.append(["Pin", "Name", "Type", "Side", "Unit", "Style", "Hidden"])
    for p in c.pins:
        rows.append([p.number, _clean(p.name), p.type, p.side, str(p.unit), p.style,
                     "yes" if p.hidden else ""])
    return rows


def generate_symbol(c: Component, lib_path: Path, footprint: str) -> Path:
    """Adds (or replaces) the symbol in the `lib_path` library."""
    lib_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = Path(tmp) / "part.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(to_kipart_rows(c, footprint))
        with contextlib.redirect_stdout(io.StringIO()):  # KiPart prints "Created symbol library..."
            row_file_to_symbol_lib_file(
                str(csv_path), str(lib_path),
                sort_by="row", overwrite=True, merge=lib_path.exists(),
                bundle=True, justify="left",
            )
    _hide_props(lib_path)
    return lib_path
