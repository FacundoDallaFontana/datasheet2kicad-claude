"""Sanity checks on what the AI extracted.

Errors (`error`) trigger a retry of the extraction and are shown in red in the GUI;
warnings (`warning`) are only displayed.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Literal

from .schema import Component, Dim, Package


@dataclass
class Issue:
    severity: Literal["error", "warning"]
    field: str  # "pins", "pins[3]", "package.body_x", ...
    message: str

    def __str__(self) -> str:
        return f"[{self.severity}] {self.field}: {self.message}"


def check(c: Component) -> list[Issue]:
    issues: list[Issue] = []
    if c.status != "ok":
        return issues
    issues += _check_pins(c)
    if c.package is None:
        issues.append(Issue("error", "package", "The package is missing."))
    else:
        issues += _check_package(c.package)
        issues += _check_pins_vs_package(c)
    return issues


def errors_as_feedback(issues: list[Issue]) -> list[str]:
    return [f"{i.field}: {i.message}" for i in issues if i.severity == "error"]


def _check_pins(c: Component) -> list[Issue]:
    issues = []
    if not c.pins:
        return [Issue("error", "pins", "No pins were extracted.")]
    counts = Counter(p.number for p in c.pins)
    for number, n in counts.items():
        if n > 1:
            issues.append(Issue("error", "pins", f"Pin number {number} appears {n} times."))
    for i, p in enumerate(c.pins):
        if not p.name.strip():
            issues.append(Issue("error", f"pins[{i}]", f"Pin {p.number} has no name."))
    return issues


def _check_dim(name: str, d: Dim, required: bool) -> list[Issue]:
    if not d.has_value():
        return [Issue("error" if required else "warning", f"package.{name}", "Value missing.")]
    issues = []
    values = [v for v in (d.min, d.nom, d.max) if v is not None]
    if values != sorted(values):
        issues.append(Issue("error", f"package.{name}", f"min ≤ nom ≤ max does not hold ({d})."))
    if any(v <= 0 for v in values):
        issues.append(Issue("error", f"package.{name}", "Non-positive value."))
    if any(v > 60 for v in values):
        issues.append(Issue("error", f"package.{name}",
                            "Value > 60 mm: is it in mils or inches instead of mm?"))
    return issues


def _check_package(pkg: Package) -> list[Issue]:
    issues: list[Issue] = []
    if pkg.family == "other":
        return [Issue("warning", "package.family",
                      "Unsupported family: no footprint will be generated (library match only).")]
    issues += _check_dim("body_x", pkg.body_x, True)
    issues += _check_dim("body_y", pkg.body_y, True)
    issues += _check_dim("lead_width", pkg.lead_width, True)
    issues += _check_dim("lead_len", pkg.lead_len, True)
    if pkg.family in ("gullwing", "tab"):
        issues += _check_dim("overall_x", pkg.overall_x, pkg.num_pins_y > 0)
    if pkg.family == "gullwing" and pkg.num_pins_x > 0:
        issues += _check_dim("overall_y", pkg.overall_y, True)
    if pkg.pitch is None or pkg.pitch <= 0:
        issues.append(Issue("error", "package.pitch", "The pitch is missing."))
        return issues

    positions = 2 * (pkg.num_pins_x + pkg.num_pins_y)
    if pkg.family == "tab":
        positions = pkg.num_pins_y
    if positions - len(pkg.deleted_pins) != pkg.pin_count:
        issues.append(Issue("error", "package.num_pins_x/num_pins_y",
                            f"The grid ({positions} positions - {len(pkg.deleted_pins)} deleted) "
                            f"does not match pin_count={pkg.pin_count}."))

    # The pin rows must fit in the body.
    for n, body, name in ((pkg.num_pins_y, pkg.body_y, "body_y"), (pkg.num_pins_x, pkg.body_x, "body_x")):
        size = body.hi()
        if n > 1 and size is not None and pkg.pitch * (n - 1) >= size + 0.5:
            issues.append(Issue("error", f"package.{name}",
                                f"{n} pins at pitch {pkg.pitch} span {pkg.pitch * (n - 1):.2f} mm, "
                                f"more than the body ({size} mm). Wrong pitch or pins per side?"))
    lw = pkg.lead_width.hi()
    if lw is not None and pkg.num_pins_y > 1 and lw >= pkg.pitch:
        issues.append(Issue("error", "package.lead_width", f"Lead width {lw} ≥ pitch {pkg.pitch}."))

    if pkg.family in ("gullwing", "tab"):
        ov, bx = pkg.overall_x.lo(), pkg.body_x.hi()
        if ov is not None and bx is not None and ov <= bx:
            issues.append(Issue("error", "package.overall_x",
                                f"overall_x ({ov}) must be larger than body_x ({bx}); are E and E1 swapped?"))

    if pkg.ep:
        for axis, body in (("x", pkg.body_x), ("y", pkg.body_y)):
            ep_d: Dim = getattr(pkg.ep, axis)
            if not ep_d.has_value():
                issues.append(Issue("error", f"package.ep.{axis}", "The EP size is missing."))
            elif body.lo() is not None and (ep_d.hi() or 0) >= body.lo():
                issues.append(Issue("error", f"package.ep.{axis}", "The EP is larger than the body."))
    if pkg.family == "tab" and pkg.tab is None:
        issues.append(Issue("error", "package.tab", "Tab package but the tab dimensions are missing."))
    return issues


def lead_numbers(pkg: Package) -> list[str]:
    """Numbers of the physical leads. The tab family is not renumbered: number = position."""
    if pkg.family == "tab":
        return [str(i) for i in range(1, pkg.num_pins_y + 1) if i not in pkg.deleted_pins]
    return [str(i) for i in range(1, pkg.pin_count + 1)]


def _check_pins_vs_package(c: Component) -> list[Issue]:
    pkg = c.package
    assert pkg is not None
    expected = pkg.pin_count + (1 if pkg.ep else 0) + (1 if pkg.tab else 0)
    numbers = {p.number for p in c.pins}
    issues = []
    # An EP/tab may share its number with an existing lead (e.g. SOT-223 with tab = pin 2).
    shared = sum(1 for extra in (pkg.ep, pkg.tab) if extra and extra.number in lead_numbers(pkg))
    if len(numbers) != expected - shared:
        issues.append(Issue("error", "pins",
                            f"There are {len(numbers)} distinct pin numbers but the package has "
                            f"{expected - shared} pads."))
    for extra, label in ((pkg.ep, "EP"), (pkg.tab, "tab")):
        if extra and extra.number not in numbers:
            issues.append(Issue("error", "pins", f"The {label} (pin {extra.number}) is not in the pin list."))
    return issues
