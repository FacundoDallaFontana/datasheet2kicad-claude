"""SOT-223 / TO-252 / TO-263: leads on the left and tab on the right, built with KicadModTree.

The official generator does not cover these packages from a generic spec, so we compute the land
pattern with the IPC-7351B rules (nominal density) and draw the layers following KLC.
"""
from __future__ import annotations

import math
import re
from pathlib import Path

from ..schema import Package
from . import init_kfg

TOE, HEEL, SIDE = 0.35, 0.35, 0.05   # IPC-7351B gullwing, nominal density
TAB_HEEL = 0.1
DPAK_TAB_PROTRUSION = 1.0
COURTYARD = 0.25
SILK_OFFSET, SILK_W, FAB_W, CRT_W = 0.11, 0.12, 0.1, 0.05


def _r(v: float, grid: float = 0.01) -> float:
    return round(round(v / grid) * grid, 4)


def _ceil(v: float, grid: float = 0.01) -> float:
    return round(math.ceil(v / grid - 1e-9) * grid, 4)


def footprint_name(pkg: Package) -> str:
    base = re.sub(r"[^A-Za-z0-9\-]", "", pkg.name.split()[0]) or "TAB"
    tab_suffix = f"_TabPin{pkg.tab.number}" if pkg.tab else ""
    return f"{base}{tab_suffix}"


def build(pkg: Package, out_dir: Path) -> Path:
    init_kfg(out_dir)  # loads the global KLC config used by KicadModTree
    from KicadModTree import (Footprint, FootprintType, KicadFileHandler, Line, Pad, Property,
                              Rectangle, RoundRadiusHandler, Text)

    assert pkg.tab and pkg.pitch
    rrh = RoundRadiusHandler(radius_ratio=0.25, maximum_radius=0.25)
    ov_lo, ov_hi = pkg.overall_x.lo(), pkg.overall_x.hi()
    assert ov_lo and ov_hi

    # --- lead pads (left) ---
    outer = ov_hi / 2 + TOE
    inner = ov_lo / 2 - pkg.lead_len.hi() - HEEL
    lead_len_pad, lead_x = outer - inner, -(outer + inner) / 2
    lead_w = pkg.lead_width.hi() + 2 * SIDE
    n = pkg.num_pins_y

    # --- tab pad (right) ---
    tab_outer = ov_hi / 2 + TOE
    tab_inner = ov_lo / 2 - pkg.tab.length.hi() - TAB_HEEL
    tab_len_pad, tab_x = tab_outer - tab_inner, (tab_outer + tab_inner) / 2
    tab_w = pkg.tab.width.hi() + 2 * SIDE

    name = footprint_name(pkg)
    fp = Footprint(name, FootprintType.SMD)
    fp.setDescription(f"{pkg.name}, {pkg.pin_count} leads + tab, generated from datasheet by dsgen")
    fp.setTags(f"{pkg.name.split()[0]} tab")

    pads_bbox = [lead_x - lead_len_pad / 2, -tab_w / 2, tab_x + tab_len_pad / 2, tab_w / 2]
    for i in range(n):
        if (i + 1) in pkg.deleted_pins:
            continue
        y = (i - (n - 1) / 2) * pkg.pitch
        fp.append(Pad(number=str(i + 1), type=Pad.TYPE_SMT, shape=Pad.SHAPE_ROUNDRECT,
                      at=[_r(lead_x), _r(y)], size=[_r(lead_len_pad), _r(lead_w)],
                      layers=Pad.LAYERS_SMT, round_radius_handler=rrh))
        pads_bbox[1] = min(pads_bbox[1], y - lead_w / 2)
        pads_bbox[3] = max(pads_bbox[3], y + lead_w / 2)
    fp.append(Pad(number=pkg.tab.number, type=Pad.TYPE_SMT, shape=Pad.SHAPE_ROUNDRECT,
                  at=[_r(tab_x), 0], size=[_r(tab_len_pad), _r(tab_w)],
                  layers=Pad.LAYERS_SMT, round_radius_handler=rrh))

    # --- fab: body with pin 1 chamfer ---
    # SOT-223: the tab is just another lead, so the body is centered. DPAK/D2PAK: the tab is the
    # heatsink under the body and sticks out ~1 mm (JEDEC TO-252 L3), so the body shifts right.
    bx, by = pkg.body_x.nominal() / 2, pkg.body_y.nominal() / 2
    heatsink_tab = pkg.tab.length.hi() > 2 * pkg.lead_len.hi()
    cx = (pkg.overall_x.nominal() / 2 - DPAK_TAB_PROTRUSION - bx) if heatsink_tab else 0.0
    ch = min(1.0, bx / 2, by / 2)
    fab = [(-bx + ch, -by), (bx, -by), (bx, by), (-bx, by), (-bx, -by + ch), (-bx + ch, -by)]
    fab = [(x + cx, y) for x, y in fab]
    for a, b in zip(fab, fab[1:]):
        fp.append(Line(start=[_r(a[0]), _r(a[1])], end=[_r(b[0]), _r(b[1])], layer="F.Fab", width=FAB_W))
    body_x0, body_x1 = cx - bx, cx + bx

    # --- silk: top and bottom body edges; the top one extends to pin 1 ---
    sy = by + SILK_OFFSET
    if sy > pads_bbox[3] + 0.2:  # only if it does not overlap pads
        fp.append(Line(start=[_r(lead_x - lead_len_pad / 2), _r(-sy)],
                       end=[_r(body_x1 + SILK_OFFSET), _r(-sy)], layer="F.SilkS", width=SILK_W))
        fp.append(Line(start=[_r(body_x0 - SILK_OFFSET), _r(sy)], end=[_r(body_x1 + SILK_OFFSET), _r(sy)],
                       layer="F.SilkS", width=SILK_W))

    # --- courtyard ---
    cx0 = min(pads_bbox[0], body_x0) - COURTYARD
    cx1 = max(pads_bbox[2], body_x1) + COURTYARD
    cy = max(pads_bbox[3], by) + COURTYARD
    fp.append(Rectangle(start=[-_ceil(-cx0, 0.01), -_ceil(cy)], end=[_ceil(cx1), _ceil(cy)],
                        layer="F.CrtYd", width=CRT_W))

    fp.append(Property(name=Property.REFERENCE, text="REF**", at=[0, _r(-cy - 1)], layer="F.SilkS"))
    fp.append(Property(name=Property.VALUE, text=name, at=[0, _r(cy + 1)], layer="F.Fab"))
    fp.append(Text(text="${REFERENCE}", at=[0, 0], layer="F.Fab", size=[0.8, 0.8], thickness=0.12))

    lib = out_dir / "Package_TO_SOT_SMD.pretty"
    lib.mkdir(parents=True, exist_ok=True)
    path = lib / f"{name}.kicad_mod"
    KicadFileHandler(fp).writeFile(path)
    return path
