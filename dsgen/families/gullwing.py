"""SOIC / SSOP / TSSOP / QFP / SOT-23 with the official IPC gullwing generator."""
from __future__ import annotations

from pathlib import Path

from ..schema import Package
from . import device_type, init_kfg, single_output, tol


def to_spec(pkg: Package) -> dict:
    is_sot = "SOT" in pkg.name.upper() or "SC-70" in pkg.name.upper() or "SC70" in pkg.name.upper()
    spec = {
        "device_type": device_type(pkg.name, "SOIC"),
        "library_Suffix": "QFP" if pkg.num_pins_x else ("TO_SOT_SMD" if is_sot else "SO"),
        "body_size_x": tol(pkg.body_x),
        "body_size_y": tol(pkg.body_y),
        "overall_size_x": tol(pkg.overall_x),
        "lead_width": tol(pkg.lead_width),
        "lead_len": tol(pkg.lead_len),
        "pitch": pkg.pitch,
        "num_pins_x": pkg.num_pins_x,
        "num_pins_y": pkg.num_pins_y,
    }
    if pkg.overall_y.has_value():
        spec["overall_size_y"] = tol(pkg.overall_y)
    if pkg.body_height.has_value():
        spec["body_height"] = tol(pkg.body_height)
    if pkg.deleted_pins:
        spec["deleted_pins"] = list(pkg.deleted_pins)
        # Official-library style name ('SOT-23-5') instead of 'SOT-6-5_...'.
        spec["custom_name_format"] = pkg.name.split()[0].upper()
    if pkg.ep:
        spec["EP_size_x"] = tol(pkg.ep.x)
        spec["EP_size_y"] = tol(pkg.ep.y)
    return spec


def build(pkg: Package, out_dir: Path) -> Path:
    init_kfg(out_dir)
    from generators.package.gullwing.footprint import create_footprints
    from generators.package.gullwing.spec import GullwingSpec

    create_footprints(GullwingSpec(pkg.name, to_spec(pkg), "dsgen.yaml"), "dsgen")
    return single_output(out_dir)
