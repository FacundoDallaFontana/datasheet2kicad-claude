"""Chequeos de sanidad sobre lo extraído por la IA.

Los errores (`error`) disparan un reintento de la extracción y se marcan en rojo en la GUI;
las advertencias (`warning`) solo se muestran.
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
        issues.append(Issue("error", "package", "Falta el package."))
    else:
        issues += _check_package(c.package)
        issues += _check_pins_vs_package(c)
    return issues


def errors_as_feedback(issues: list[Issue]) -> list[str]:
    return [f"{i.field}: {i.message}" for i in issues if i.severity == "error"]


def _check_pins(c: Component) -> list[Issue]:
    issues = []
    if not c.pins:
        return [Issue("error", "pins", "No se extrajo ningún pin.")]
    counts = Counter(p.number for p in c.pins)
    for number, n in counts.items():
        if n > 1:
            issues.append(Issue("error", "pins", f"El número de pin {number} aparece {n} veces."))
    for i, p in enumerate(c.pins):
        if not p.name.strip():
            issues.append(Issue("error", f"pins[{i}]", f"El pin {p.number} no tiene nombre."))
    return issues


def _check_dim(name: str, d: Dim, required: bool) -> list[Issue]:
    if not d.has_value():
        return [Issue("error" if required else "warning", f"package.{name}", "Falta el valor.")]
    issues = []
    values = [v for v in (d.min, d.nom, d.max) if v is not None]
    if values != sorted(values):
        issues.append(Issue("error", f"package.{name}", f"No se cumple min ≤ nom ≤ max ({d})."))
    if any(v <= 0 for v in values):
        issues.append(Issue("error", f"package.{name}", "Valor no positivo."))
    if any(v > 60 for v in values):
        issues.append(Issue("error", f"package.{name}",
                            "Valor > 60 mm: ¿está en mils o pulgadas en vez de mm?"))
    return issues


def _check_package(pkg: Package) -> list[Issue]:
    issues: list[Issue] = []
    if pkg.family == "other":
        return [Issue("warning", "package.family",
                      "Familia no soportada: no se generará footprint (solo match con la librería).")]
    issues += _check_dim("body_x", pkg.body_x, True)
    issues += _check_dim("body_y", pkg.body_y, True)
    issues += _check_dim("lead_width", pkg.lead_width, True)
    issues += _check_dim("lead_len", pkg.lead_len, True)
    if pkg.family in ("gullwing", "tab"):
        issues += _check_dim("overall_x", pkg.overall_x, pkg.num_pins_y > 0)
    if pkg.family == "gullwing" and pkg.num_pins_x > 0:
        issues += _check_dim("overall_y", pkg.overall_y, True)
    if pkg.pitch is None or pkg.pitch <= 0:
        issues.append(Issue("error", "package.pitch", "Falta el pitch."))
        return issues

    positions = 2 * (pkg.num_pins_x + pkg.num_pins_y)
    if pkg.family == "tab":
        positions = pkg.num_pins_y
    if positions - len(pkg.deleted_pins) != pkg.pin_count:
        issues.append(Issue("error", "package.num_pins_x/num_pins_y",
                            f"La grilla ({positions} posiciones - {len(pkg.deleted_pins)} borradas) "
                            f"no coincide con pin_count={pkg.pin_count}."))

    # Las filas de pines tienen que entrar en el cuerpo.
    for n, body, name in ((pkg.num_pins_y, pkg.body_y, "body_y"), (pkg.num_pins_x, pkg.body_x, "body_x")):
        size = body.hi()
        if n > 1 and size is not None and pkg.pitch * (n - 1) >= size + 0.5:
            issues.append(Issue("error", f"package.{name}",
                                f"{n} pines a pitch {pkg.pitch} ocupan {pkg.pitch * (n - 1):.2f} mm, "
                                f"más que el cuerpo ({size} mm). ¿Pitch o cantidad por lado mal?"))
    lw = pkg.lead_width.hi()
    if lw is not None and pkg.num_pins_y > 1 and lw >= pkg.pitch:
        issues.append(Issue("error", "package.lead_width", f"Ancho de terminal {lw} ≥ pitch {pkg.pitch}."))

    if pkg.family in ("gullwing", "tab"):
        ov, bx = pkg.overall_x.lo(), pkg.body_x.hi()
        if ov is not None and bx is not None and ov <= bx:
            issues.append(Issue("error", "package.overall_x",
                                f"overall_x ({ov}) debe ser mayor que body_x ({bx}); ¿E y E1 invertidos?"))

    if pkg.ep:
        for axis, body in (("x", pkg.body_x), ("y", pkg.body_y)):
            ep_d: Dim = getattr(pkg.ep, axis)
            if not ep_d.has_value():
                issues.append(Issue("error", f"package.ep.{axis}", "Falta el tamaño del EP."))
            elif body.lo() is not None and (ep_d.hi() or 0) >= body.lo():
                issues.append(Issue("error", f"package.ep.{axis}", "El EP es más grande que el cuerpo."))
    if pkg.family == "tab" and pkg.tab is None:
        issues.append(Issue("error", "package.tab", "Package con tab pero faltan las medidas del tab."))
    return issues


def lead_numbers(pkg: Package) -> list[str]:
    """Números de los leads físicos. En la familia tab no se renumera: número = posición."""
    if pkg.family == "tab":
        return [str(i) for i in range(1, pkg.num_pins_y + 1) if i not in pkg.deleted_pins]
    return [str(i) for i in range(1, pkg.pin_count + 1)]


def _check_pins_vs_package(c: Component) -> list[Issue]:
    pkg = c.package
    assert pkg is not None
    expected = pkg.pin_count + (1 if pkg.ep else 0) + (1 if pkg.tab else 0)
    numbers = {p.number for p in c.pins}
    issues = []
    # Con EP/tab el número puede coincidir con un lead existente (p.ej. SOT-223 con tab = pin 2).
    shared = sum(1 for extra in (pkg.ep, pkg.tab) if extra and extra.number in lead_numbers(pkg))
    if len(numbers) != expected - shared:
        issues.append(Issue("error", "pins",
                            f"Hay {len(numbers)} números de pin distintos pero el package tiene "
                            f"{expected - shared} pads."))
    for extra, label in ((pkg.ep, "EP"), (pkg.tab, "tab")):
        if extra and extra.number not in numbers:
            issues.append(Issue("error", "pins", f"El {label} (pin {extra.number}) no está en la lista de pines."))
    return issues
