"""Generator tests without AI: standard packages with known JEDEC dimensions.

Each case must (a) generate a footprint, (b) match the expected official KiCad footprint and
(c) produce files that kicad-cli can open.
"""
from __future__ import annotations

import subprocess

import pytest

from dsgen.footprint_gen import generate_footprint
from dsgen.kicad_env import find_kicad
from dsgen.schema import Component, Dim, ExposedPad, Package, Pin, Tab
from dsgen.symbol_gen import generate_symbol
from dsgen.validate import check

KICAD = find_kicad()
needs_kicad = pytest.mark.skipif(KICAD is None, reason="KiCad no instalado")


def D(lo=None, nom=None, hi=None):
    return Dim(min=lo, nom=nom, max=hi)


SOIC8 = Package(family="gullwing", name="SOIC-8 (D)", pin_count=8, pitch=1.27, num_pins_y=4,
                body_x=D(3.8, None, 4.0), body_y=D(4.8, None, 5.0), overall_x=D(5.8, None, 6.2),
                body_height=D(hi=1.75), lead_width=D(0.31, None, 0.51), lead_len=D(0.4, None, 1.27))
TSSOP14 = Package(family="gullwing", name="TSSOP-14 (PW)", pin_count=14, pitch=0.65, num_pins_y=7,
                  body_x=D(4.3, 4.4, 4.5), body_y=D(4.9, 5.0, 5.1), overall_x=D(6.2, 6.4, 6.6),
                  lead_width=D(0.19, None, 0.30), lead_len=D(0.45, 0.6, 0.75))
LQFP48 = Package(family="gullwing", name="LQFP-48", pin_count=48, pitch=0.5, num_pins_x=12, num_pins_y=12,
                 body_x=D(6.8, 7.0, 7.2), body_y=D(6.8, 7.0, 7.2), overall_x=D(8.8, 9.0, 9.2),
                 overall_y=D(8.8, 9.0, 9.2), lead_width=D(0.17, 0.22, 0.27), lead_len=D(0.45, 0.6, 0.75))
SOT23_5 = Package(family="gullwing", name="SOT-23-5 (DBV)", pin_count=5, pitch=0.95, num_pins_y=3,
                  deleted_pins=[5], body_x=D(nom=1.6), body_y=D(nom=2.9), overall_x=D(nom=2.8),
                  lead_width=D(0.3, None, 0.5), lead_len=D(0.3, 0.45, 0.6))
QFN16 = Package(family="nolead", name="QFN-16", pin_count=16, pitch=0.5, num_pins_x=4, num_pins_y=4,
                body_x=D(2.9, 3.0, 3.1), body_y=D(2.9, 3.0, 3.1), lead_width=D(0.18, None, 0.3),
                lead_len=D(0.3, None, 0.5), ep=ExposedPad(number="17", x=D(nom=1.7), y=D(nom=1.7)))
SOT223 = Package(family="tab", name="SOT-223", pin_count=3, pitch=2.3, num_pins_y=3,
                 body_x=D(3.3, 3.5, 3.7), body_y=D(6.3, 6.5, 6.7), overall_x=D(6.7, 7.0, 7.3),
                 lead_width=D(0.66, None, 0.84), lead_len=D(0.9, None, 1.1),
                 tab=Tab(number="4", width=D(2.9, 3.0, 3.1), length=D(0.9, None, 1.1)))
TO252 = Package(family="tab", name="TO-252 (DPAK)", pin_count=2, pitch=2.28, num_pins_y=3, deleted_pins=[2],
                body_x=D(5.97, None, 6.22), body_y=D(6.35, None, 6.73), overall_x=D(9.4, None, 10.4),
                lead_width=D(0.64, None, 0.89), lead_len=D(1.4, None, 1.78),
                tab=Tab(number="2", width=D(5.21, None, 5.46), length=D(5.2, None, 6.2)))

EXPECTED = [
    (SOIC8, "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"),
    (TSSOP14, "Package_SO:TSSOP-14_4.4x5mm_P0.65mm"),
    (LQFP48, "Package_QFP:LQFP-48_7x7mm_P0.5mm"),
    (SOT23_5, "Package_TO_SOT_SMD:SOT-23-5"),
    (QFN16, "Package_DFN_QFN:QFN-16-1EP_3x3mm_P0.5mm_EP1.7x1.7mm"),
]


@pytest.mark.parametrize("pkg", [SOIC8, TSSOP14, LQFP48, SOT23_5, QFN16, SOT223, TO252], ids=lambda p: p.name)
def test_generates_and_loads(pkg, tmp_path):
    res = generate_footprint(pkg, "dsgen", tmp_path, KICAD, use_official=False)
    assert res.generated_path and res.generated_path.exists()
    if KICAD:
        r = subprocess.run([str(KICAD.cli), "fp", "export", "svg", str(res.generated_path.parent),
                            "-o", str(tmp_path / "svg")], capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr


@needs_kicad
@pytest.mark.parametrize("pkg,lib_id", EXPECTED, ids=lambda x: getattr(x, "name", ""))
def test_matches_official(pkg, lib_id, tmp_path):
    res = generate_footprint(pkg, "dsgen", tmp_path, KICAD)
    assert res.match is not None
    assert res.match.accepted, res.match.describe()
    assert res.lib_id == lib_id, res.match.describe()


@needs_kicad
@pytest.mark.parametrize("pkg,prefix", [(SOT223, "Package_TO_SOT_SMD:SOT-223"),
                                        (TO252, "Package_TO_SOT_SMD:TO-252-2")], ids=["SOT223", "TO252"])
def test_tab_matches_official(pkg, prefix, tmp_path):
    res = generate_footprint(pkg, "dsgen", tmp_path, KICAD)
    assert res.match is not None and res.match.lib_id == prefix, res.match and res.match.describe()


def _ne555() -> Component:
    names = [("GND", "power_in", "bottom"), ("TRIG", "input", "left"), ("OUT", "output", "right"),
             ("~{RESET}", "input", "left"), ("CONT", "input", "left"), ("THRES", "input", "left"),
             ("DISCH", "open_collector", "right"), ("VCC", "power_in", "top")]
    return Component(status="ok", part_number="NE555DR", symbol_name="NE555D",
                     pins=[Pin(number=str(i + 1), name=n, type=t, side=s) for i, (n, t, s) in enumerate(names)],
                     package=SOIC8)


def test_validate_ok():
    assert [i for i in check(_ne555()) if i.severity == "error"] == []


def test_validate_catches_errors():
    c = _ne555()
    c.pins[1].number = "1"                     # duplicated number
    c.package = SOIC8.model_copy(update={"pitch": 2.54, "overall_x": D(3.0, None, 3.5)})
    fields = {i.field for i in check(c) if i.severity == "error"}
    assert "pins" in fields and "package.overall_x" in fields and "package.body_y" in fields


def test_symbol(tmp_path):
    lib = generate_symbol(_ne555(), tmp_path / "dsgen.kicad_sym", "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm")
    text = lib.read_text(encoding="utf-8")
    assert '(symbol "NE555D"' in text and "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm" in text
    if KICAD:
        r = subprocess.run([str(KICAD.cli), "sym", "export", "svg", str(lib), "-o", str(tmp_path / "svg")],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
