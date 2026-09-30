"""Uso:
    python -m dsgen                                        # abre la GUI
    python -m dsgen datasheet.pdf --part NE555DR -o out/   # extrae con IA y genera
    python -m dsgen --from-json out/NE555D.component.json -o out/   # re-genera sin IA
    python -m dsgen --usage                                # consumo acumulado de Claude
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .extractor import MODELS, ExtractionError
from .schema import Component


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="dsgen", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf", nargs="?", type=Path, help="Datasheet en PDF")
    ap.add_argument("--part", help="Part number / código de pedido completo (obligatorio con PDF)")
    ap.add_argument("-o", "--out", type=Path, default=Path("out"), help="Carpeta de salida")
    ap.add_argument("--lib", default="dsgen", help="Nombre de la librería (.kicad_sym / .pretty)")
    ap.add_argument("--model", choices=MODELS, default="sonnet")
    ap.add_argument("--force", action="store_true", help="Ignorar la caché y volver a extraer")
    ap.add_argument("--no-official", action="store_true",
                    help="Generar siempre el footprint aunque exista uno oficial equivalente")
    ap.add_argument("--from-json", type=Path, help="Re-generar desde un component.json editado")
    ap.add_argument("--usage", action="store_true", help="Mostrar el consumo acumulado de Claude y salir")
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    if args.usage:
        from . import usage
        print(usage.summary().describe())
        print(f"Detalle por llamada: {usage.USAGE_FILE}")
        return 0

    if not args.pdf and not args.from_json:
        from .gui import run_gui
        run_gui()
        return 0

    from .pipeline import extract_component, generate

    if args.from_json:
        component = Component.model_validate_json(args.from_json.read_text(encoding="utf-8"))
    else:
        if not args.part:
            ap.error("--part es obligatorio: el datasheet suele cubrir varias variantes y packages.")
        try:
            component, issues = extract_component(args.pdf, args.part, args.model, args.force)
        except ExtractionError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        for issue in issues:
            print(issue)
        if component.status != "ok":
            print(f"Part number {component.status}. Candidatos: {', '.join(component.candidates) or '-'}",
                  file=sys.stderr)
            return 2
    generate(component, args.out, args.lib, use_official=not args.no_official)
    return 0


if __name__ == "__main__":
    sys.exit(main())
