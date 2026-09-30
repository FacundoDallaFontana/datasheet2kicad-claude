"""Extracción de datos del datasheet lanzando Claude Code en modo headless.

Usa la suscripción de Claude Code del usuario (sin API key): `claude -p` con el prompt de
entrenamiento en prompts/extract_component.md y salida estructurada validada con --json-schema.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Optional

from pydantic import ValidationError

from . import usage
from .preprocess import PageHints
from .schema import Component, component_json_schema

PROMPT_FILE = Path(__file__).resolve().parent.parent / "prompts" / "extract_component.md"
MODELS = ("sonnet", "haiku", "opus")

Log = Callable[[str], None]


class ExtractionError(RuntimeError):
    pass


def _task_prompt(pdf_path: Path, part_number: str, hints: Optional[PageHints],
                 feedback: Optional[list[str]]) -> str:
    lines = [
        f"Datasheet: {pdf_path}",
        f"Part number (código de pedido completo): {part_number}",
    ]
    if hints:
        lines.append(f"El PDF tiene {hints.page_count} páginas.")
        for section, pages in hints.sections.items():
            if pages:
                lines.append(f"Páginas sugeridas para '{section}': {pages}")
        if hints.part_hits:
            lines.append(f"Páginas donde aparece el part number: {hints.part_hits}")
    lines.append("Seguí el procedimiento de tus instrucciones y devolvé el objeto JSON final.")
    if feedback:
        lines.append("")
        lines.append("Un intento anterior produjo datos con estos problemas; revisá esas páginas "
                     "y corregilos:")
        lines += [f"- {msg}" for msg in feedback]
    return "\n".join(lines)


def _describe_event(event: dict) -> Optional[str]:
    """Convierte un evento de stream-json en una línea legible para el log."""
    if event.get("type") != "assistant":
        return None
    parts = []
    for block in event.get("message", {}).get("content", []):
        if block.get("type") == "tool_use" and block.get("name") == "Read":
            inp = block.get("input", {})
            pages = f" (págs. {inp['pages']})" if inp.get("pages") else ""
            parts.append(f"Leyendo {Path(inp.get('file_path', '?')).name}{pages}")
        elif block.get("type") == "tool_use":
            parts.append(f"Herramienta: {block.get('name')}")
        elif block.get("type") == "text" and block.get("text", "").strip():
            parts.append(block["text"].strip().splitlines()[0][:160])
    return " | ".join(parts) or None


def extract(pdf_path: Path, part_number: str, model: str = "sonnet",
            hints: Optional[PageHints] = None, feedback: Optional[list[str]] = None,
            log: Log = print) -> Component:
    claude = shutil.which("claude")
    if not claude:
        raise ExtractionError("No se encontró el ejecutable `claude` en el PATH.")
    pdf_path = pdf_path.resolve()

    cmd = [
        claude, "-p", _task_prompt(pdf_path, part_number, hints, feedback),
        "--model", model,
        "--append-system-prompt-file", str(PROMPT_FILE),
        "--json-schema", json.dumps(component_json_schema(), separators=(",", ":")),
        "--output-format", "stream-json", "--verbose",
        "--tools", "Read",
        "--allowedTools", "Read",
        "--permission-mode", "dontAsk",
        "--add-dir", str(pdf_path.parent),
        "--no-session-persistence",
    ]
    log(f"Lanzando Claude Code ({model})...")
    proc = subprocess.Popen(cmd, cwd=pdf_path.parent, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, encoding="utf-8",
                            errors="replace")
    result: Optional[dict] = None
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "result":
            result = event
        elif (msg := _describe_event(event)):
            log(f"  {msg}")
    stderr = proc.stderr.read() if proc.stderr else ""
    proc.wait()

    if result is None:
        raise ExtractionError(f"Claude terminó sin resultado (código {proc.returncode}). {stderr[-800:]}")
    attempt = 2 if feedback else 1
    if result.get("is_error") or result.get("subtype") != "success":
        usage.record(pdf_path, part_number, model, attempt, result, "error")
        raise ExtractionError(f"Claude devolvió un error: {result.get('subtype')} "
                              f"{str(result.get('result', ''))[:800]}")

    data = result.get("structured_output")
    status = data.get("status", "?") if isinstance(data, dict) else "?"
    row = usage.record(pdf_path, part_number, model, attempt, result, status)
    log(f"Extracción terminada en {row['turns']} turnos, {row['duration_s']} s · tokens: "
        f"{row['input_tokens'] + row['cache_read_tokens'] + row['cache_creation_tokens']:,} entrada / "
        f"{row['output_tokens']:,} salida · costo equivalente ≈ USD {row['cost_usd']:.3f}")

    if data is None:
        try:
            data = json.loads(result.get("result", ""))
        except json.JSONDecodeError as e:
            raise ExtractionError("La respuesta de Claude no es JSON válido.") from e
    try:
        component = Component.model_validate(data)
    except ValidationError as e:
        raise ExtractionError(f"El JSON no cumple el schema: {e}") from e
    component.part_number = component.part_number or part_number
    return component
