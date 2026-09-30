"""Matches a generated footprint against the official KiCad library.

The pad geometry is compared (number, position and size, normalized to the center of the
pad set), not the name, so it does not matter what the datasheet calls the package.
"""
from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .kicad_env import KicadInstall

LIBS = ("Package_SO", "Package_SON", "Package_DFN_QFN", "Package_QFP", "Package_TO_SOT_SMD")
INDEX_DIR = Path.home() / ".dsgen"

_PAD_RE = re.compile(
    r'\(pad\s+"([^"]*)"\s+(smd|thru_hole)\s+\w+\s*'
    r'\(at\s+(-?[\d.]+)\s+(-?[\d.]+)(?:\s+(-?[\d.]+))?\)\s*'
    r'\(size\s+([\d.]+)\s+([\d.]+)\)')

# Tolerances (mm) for accepting an official footprint as equivalent.
TOLERANCES = {
    "ipc": {"pos": 0.10, "size": 0.15, "ep_size": 0.35},   # gullwing / nolead (same generator)
    "tab": {"pos": 0.30, "size": 0.70, "ep_size": 0.90},   # the official tab footprints are hand-made
}

Pad = tuple[str, float, float, float, float]  # number, x, y, w, h


def parse_pads(text: str) -> list[Pad]:
    pads = []
    for num, _kind, x, y, rot, w, h in _PAD_RE.findall(text):
        if not num:
            continue  # paste-only / unconnected pads
        w_f, h_f = float(w), float(h)
        if rot and round(float(rot)) % 180 == 90:
            w_f, h_f = h_f, w_f
        pads.append((num, float(x), float(y), w_f, h_f))
    if not pads:
        return pads
    xs = [p[1] - p[3] / 2 for p in pads] + [p[1] + p[3] / 2 for p in pads]
    ys = [p[2] - p[4] / 2 for p in pads] + [p[2] + p[4] / 2 for p in pads]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    return sorted((n, x - cx, y - cy, w, h) for n, x, y, w, h in pads)


def _signature(pads: list[Pad]) -> str:
    counts: dict[str, int] = defaultdict(int)
    for p in pads:
        counts[p[0]] += 1
    return ",".join(f"{k}x{v}" for k, v in sorted(counts.items()))


def load_index(kicad: KicadInstall) -> dict[str, list[Pad]]:
    cache = INDEX_DIR / f"fp_index_{kicad.version}.json"
    if cache.exists():
        return {k: [tuple(p) for p in v] for k, v in json.loads(cache.read_text()).items()}
    index: dict[str, list[Pad]] = {}
    for lib in LIBS:
        lib_dir = kicad.footprint_dir / f"{lib}.pretty"
        for f in sorted(lib_dir.glob("*.kicad_mod")):
            pads = parse_pads(f.read_text(encoding="utf-8", errors="replace"))
            if pads:
                index[f"{lib}:{f.stem}"] = pads
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(index))
    return index


@dataclass
class LibMatch:
    lib_id: str           # "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"
    pos_err: float        # max pad position deviation (mm)
    size_err: float       # max size deviation of regular pads (mm)
    ep_size_err: float    # size deviation of the largest pad (EP / tab)
    accepted: bool

    def describe(self) -> str:
        verdict = "equivalent" if self.accepted else "rejected"
        return (f"{self.lib_id} ({verdict}: position ±{self.pos_err:.2f} mm, "
                f"pads ±{self.size_err:.2f} mm, EP/tab ±{self.ep_size_err:.2f} mm)")


def _compare(a: list[Pad], b: list[Pad]) -> tuple[float, float, float]:
    by_num_a, by_num_b = defaultdict(list), defaultdict(list)
    for p in a:
        by_num_a[p[0]].append(p)
    for p in b:
        by_num_b[p[0]].append(p)
    biggest = max(a, key=lambda p: p[3] * p[4])
    pos_err = size_err = ep_err = 0.0
    for num, pads_a in by_num_a.items():
        for pa, pb in zip(sorted(pads_a), sorted(by_num_b[num])):
            pos_err = max(pos_err, math.hypot(pa[1] - pb[1], pa[2] - pb[2]))
            s = max(abs(pa[3] - pb[3]), abs(pa[4] - pb[4]))
            if pa is biggest and pa[3] * pa[4] > 2 * min(p[3] * p[4] for p in a):
                ep_err = max(ep_err, s)
            else:
                size_err = max(size_err, s)
    return pos_err, size_err, ep_err


def _name_rank(lib_id: str, preferred_name: str) -> int:
    """0 = same name, 1 = same package type (prefix before the first '-'), 2 = other."""
    name = lib_id.split(":", 1)[1]
    if name == preferred_name:
        return 0
    prefix = preferred_name.split("-")[0].upper()
    return 1 if prefix and name.upper().split("-")[0] == prefix else 2


def find_match(generated_text: str, kicad: KicadInstall, family: str,
               preferred_name: str = "") -> Optional[LibMatch]:
    """Returns the closest official footprint (accepted or not), or None if there are no candidates.

    Among accepted candidates, the one with the same name or package type is preferred
    (QFN and LQFN can have identical pads), then the one with the smallest error.
    """
    pads = parse_pads(generated_text)
    if not pads:
        return None
    sig = _signature(pads)
    tol = TOLERANCES["tab" if family == "tab" else "ipc"]
    best, best_key = None, None
    for lib_id, cand in load_index(kicad).items():
        if _signature(cand) != sig:
            continue
        pos, size, ep = _compare(pads, cand)
        accepted = pos <= tol["pos"] and size <= tol["size"] and ep <= tol["ep_size"]
        err = pos + size + 0.5 * ep
        key = (not accepted, _name_rank(lib_id, preferred_name) if accepted else 0, err)
        if best_key is None or key < best_key:
            best, best_key = LibMatch(lib_id, pos, size, ep, accepted), key
    return best
