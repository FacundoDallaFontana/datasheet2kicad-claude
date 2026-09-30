"""Orquestación: PDF + part number -> Component (IA) -> símbolo + footprint."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from . import cache
from .extractor import extract
from .footprint_gen import FootprintResult, UnsupportedPackage, generate_footprint
from .kicad_env import find_kicad
from .preprocess import find_relevant_pages
from .schema import Component
from .symbol_gen import generate_symbol
from .validate import Issue, check, errors_as_feedback

Log = Callable[[str], None]


def extract_component(pdf: Path, part_number: str, model: str = "sonnet", force: bool = False,
                      log: Log = print) -> tuple[Component, list[Issue]]:
    if not force and (cached := cache.load(pdf, part_number)):
        log("Usando extracción cacheada (marcá 'forzar re-extracción' para volver a llamar a Claude).")
        return cached, check(cached)

    hints = find_relevant_pages(pdf, part_number)
    log(f"PDF de {hints.page_count} páginas; páginas relevantes: {hints.as_ranges() or 'ninguna detectada'}")
    component = extract(pdf, part_number, model=model, hints=hints, log=log)
    issues = check(component)

    if component.status == "ok" and (feedback := errors_as_feedback(issues)):
        log(f"Chequeos de sanidad con {len(feedback)} errores; reintentando con correcciones:")
        for msg in feedback:
            log(f"  - {msg}")
        retry = extract(pdf, part_number, model=model, hints=hints, feedback=feedback, log=log)
        retry_issues = check(retry)
        if len(errors_as_feedback(retry_issues)) <= len(feedback):
            component, issues = retry, retry_issues

    if component.status == "ok":
        cache.store(pdf, part_number, component)
    return component, issues


@dataclass
class GenerateResult:
    symbol_lib: Path
    json_path: Path
    footprint: Optional[FootprintResult]
    messages: list[str]


def _safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._\-]", "_", name) or "part"


def generate(component: Component, out_dir: Path, lib_name: str = "dsgen",
             use_official: bool = True, log: Log = print) -> GenerateResult:
    out_dir.mkdir(parents=True, exist_ok=True)
    kicad = find_kicad()
    messages: list[str] = []
    if kicad is None:
        messages.append("No se encontró KiCad: se genera el footprint sin comparar con la librería oficial.")

    fp: Optional[FootprintResult] = None
    pins_component = component
    if component.package:
        try:
            fp = generate_footprint(component.package, lib_name, out_dir, kicad, use_official)
            if fp.generated_path:
                messages.append(f"Footprint generado: {fp.generated_path.name}")
                if fp.match:
                    messages.append(f"Oficial más parecido: {fp.match.describe()}")
            else:
                messages.append(f"Se usa el footprint oficial: {fp.match.describe() if fp.match else fp.lib_id}")
            if fp.pin_renames:
                messages.append(f"Pines renumerados para coincidir con el footprint oficial: {fp.pin_renames}")
                pins_component = component.model_copy(deep=True)
                for p in pins_component.pins:
                    p.number = fp.pin_renames.get(p.number, p.number)
        except UnsupportedPackage as e:
            messages.append(f"{e} El símbolo queda sin footprint asignado.")

    symbol_lib = generate_symbol(pins_component, out_dir / f"{lib_name}.kicad_sym", fp.lib_id if fp else "")
    messages.append(f"Símbolo '{component.symbol_name or component.part_number}' en {symbol_lib.name}")

    json_path = out_dir / f"{_safe_name(component.symbol_name or component.part_number)}.component.json"
    json_path.write_text(json.dumps(component.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")
    messages.append(f"Datos extraídos guardados en {json_path.name} (editable, se puede re-generar)")
    for m in messages:
        log(m)
    return GenerateResult(symbol_lib, json_path, fp, messages)
