"""End-to-end tests on real datasheets (they call Claude, so they are opt-in).

Put the PDFs in `pdf-test/` (git-ignored, local only) together with one `<name>.case.json`
per part number to check:

    {
      "pdf": "ne555.pdf",
      "part_number": "NE555DR",
      "model": "sonnet",                        # optional
      "expect": {                               # every key is optional
        "status": "ok",                         # or "part_not_found" / "ambiguous"
        "pin_count": 8,                         # number of entries in `pins` (EP included)
        "pins": {"1": "GND", "2": "TRIG"},      # pin number -> expected name
        "package_family": "gullwing",
        "footprint": "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
        "candidates_include": ["NE555DR"],      # for part_not_found / ambiguous
        "no_errors": true                       # sanity checks without errors (default true)
      }
    }

Run with:  .venv/Scripts/python -m pytest -m ai -v
The extraction cache is used; set DSGEN_FORCE=1 to call Claude again for every case.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from dsgen.pipeline import extract_component, generate

PDF_TEST_DIR = Path(__file__).resolve().parent.parent / "pdf-test"
CASES = sorted(PDF_TEST_DIR.glob("*.case.json")) if PDF_TEST_DIR.is_dir() else []
PDFS_WITHOUT_CASE = sorted(
    {p.name for p in PDF_TEST_DIR.glob("*.pdf")} - {json.loads(c.read_text(encoding="utf-8"))["pdf"] for c in CASES}
) if PDF_TEST_DIR.is_dir() else []

pytestmark = pytest.mark.ai


def _norm(name: str) -> str:
    return re.sub(r"[^A-Z0-9/]", "", name.upper().replace("~{", "").replace("}", ""))


def _name_matches(expected: str, got: str) -> bool:
    e, g = _norm(expected), _norm(got)
    return e == g or e in g.split("/") or g in e.split("/")


@pytest.mark.parametrize("case_path", CASES, ids=[c.name.removesuffix(".case.json") for c in CASES])
def test_datasheet(case_path: Path, tmp_path: Path):
    case = json.loads(case_path.read_text(encoding="utf-8"))
    pdf = PDF_TEST_DIR / case["pdf"]
    if not pdf.exists():
        pytest.skip(f"{pdf.name} is not in pdf-test/")
    expect = case.get("expect", {})
    force = os.environ.get("DSGEN_FORCE") == "1"

    component, issues = extract_component(pdf, case["part_number"], case.get("model", "sonnet"),
                                          force=force, log=lambda _: None)
    problems: list[str] = []

    if (status := expect.get("status", "ok")) != component.status:
        pytest.fail(f"status: expected {status}, got {component.status} "
                    f"(candidates: {component.candidates}, notes: {component.notes})")
    for cand in expect.get("candidates_include", []):
        if cand not in component.candidates:
            problems.append(f"candidate {cand} missing from {component.candidates}")
    if component.status != "ok":
        assert not problems, "\n".join(problems)
        return

    if expect.get("no_errors", True):
        problems += [f"sanity check: {i}" for i in issues if i.severity == "error"]
    if "pin_count" in expect and len(component.pins) != expect["pin_count"]:
        problems.append(f"pin_count: expected {expect['pin_count']}, got {len(component.pins)}")
    got_pins = {p.number: p.name for p in component.pins}
    for number, name in expect.get("pins", {}).items():
        if number not in got_pins:
            problems.append(f"pin {number}: missing (expected {name})")
        elif not _name_matches(name, got_pins[number]):
            problems.append(f"pin {number}: expected {name}, got {got_pins[number]}")
    if "package_family" in expect:
        family = component.package.family if component.package else None
        if family != expect["package_family"]:
            problems.append(f"package_family: expected {expect['package_family']}, got {family}")

    if "footprint" in expect:
        result = generate(component, tmp_path, "dsgen", log=lambda _: None)
        got_fp = result.footprint.lib_id if result.footprint else None
        if got_fp != expect["footprint"]:
            closest = result.footprint.match.describe() if result.footprint and result.footprint.match else "-"
            problems.append(f"footprint: expected {expect['footprint']}, got {got_fp} (closest: {closest})")

    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("pdf_name", PDFS_WITHOUT_CASE)
def test_pdf_without_case(pdf_name: str):
    pytest.skip(f"pdf-test/{pdf_name} has no .case.json: create one to test it")
