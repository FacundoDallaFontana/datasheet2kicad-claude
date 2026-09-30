"""QFN / DFN / SON con el generador IPC no-lead oficial."""
from __future__ import annotations

from pathlib import Path

from ..schema import Package
from . import device_type, init_kfg, single_output, tol


def to_spec(pkg: Package) -> dict:
    spec = {
        "device_type": device_type(pkg.name, "QFN" if pkg.num_pins_x else "DFN"),
        "library": "Package_DFN_QFN",
        "ipc_class": "qfn",
        "body_size_x": tol(pkg.body_x),
        "body_size_y": tol(pkg.body_y),
        "lead_width": tol(pkg.lead_width),
        "lead_len": tol(pkg.lead_len),
        "pitch": pkg.pitch,
        "num_pins_x": pkg.num_pins_x,
        "num_pins_y": pkg.num_pins_y,
    }
    if pkg.body_height.has_value():
        spec["overall_height"] = tol(pkg.body_height)
    if pkg.deleted_pins:
        spec["deleted_pins"] = list(pkg.deleted_pins)
    if pkg.ep:
        spec["EP_size_x"] = tol(pkg.ep.x)
        spec["EP_size_y"] = tol(pkg.ep.y)
        # El EP queda como pin_count+1 (convención KLC); footprint_gen lo renumera si hace falta.
    return spec


def build(pkg: Package, out_dir: Path) -> Path:
    init_kfg(out_dir)
    from generators.package.no_lead.footprint import create_footprints
    from generators.package.no_lead.spec import NoLeadSpec

    create_footprints(NoLeadSpec(pkg.name, to_spec(pkg), "dsgen.yaml"), "dsgen")
    return single_output(out_dir)
