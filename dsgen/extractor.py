"""Extracts data from the datasheet by running Claude Code headless.

Uses the user's Claude Code login (no API key needed): `claude -p` with the instructions in
prompts/extract_component.md and structured output validated with --json-schema.
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
        f"Part number (full orderable part number): {part_number}",
    ]
    if hints:
        lines.append(f"The PDF has {hints.page_count} pages.")
        for section, pages in hints.sections.items():
            if pages:
                lines.append(f"Suggested pages for '{section}': {pages}")
        if hints.part_hits:
            lines.append(f"Pages where the part number appears: {hints.part_hits}")
    lines.append("Follow the procedure in your instructions and return the final JSON object.")
    if feedback:
        lines.append("")
        lines.append("A previous attempt produced data with these problems; check those pages "
                     "again and fix them:")
        lines += [f"- {msg}" for msg in feedback]
    return "\n".join(lines)


def _describe_event(event: dict) -> Optional[str]:
    """Turns a stream-json event into a readable log line."""
    if event.get("type") != "assistant":
        return None
    parts = []
    for block in event.get("message", {}).get("content", []):
        if block.get("type") == "tool_use" and block.get("name") == "Read":
            inp = block.get("input", {})
            pages = f" (pp. {inp['pages']})" if inp.get("pages") else ""
            parts.append(f"Reading {Path(inp.get('file_path', '?')).name}{pages}")
        elif block.get("type") == "tool_use":
            parts.append(f"Tool: {block.get('name')}")
        elif block.get("type") == "text" and block.get("text", "").strip():
            parts.append(block["text"].strip().splitlines()[0][:160])
    return " | ".join(parts) or None


def extract(pdf_path: Path, part_number: str, model: str = "sonnet",
            hints: Optional[PageHints] = None, feedback: Optional[list[str]] = None,
            log: Log = print) -> Component:
    claude = shutil.which("claude")
    if not claude:
        raise ExtractionError("The `claude` executable was not found in PATH.")
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
    log(f"Launching Claude Code ({model})...")
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
        raise ExtractionError(f"Claude finished without a result (exit code {proc.returncode}). {stderr[-800:]}")
    attempt = 2 if feedback else 1
    if result.get("is_error") or result.get("subtype") != "success":
        usage.record(pdf_path, part_number, model, attempt, result, "error")
        raise ExtractionError(f"Claude returned an error: {result.get('subtype')} "
                              f"{str(result.get('result', ''))[:800]}")

    data = result.get("structured_output")
    status = data.get("status", "?") if isinstance(data, dict) else "?"
    row = usage.record(pdf_path, part_number, model, attempt, result, status)
    log(f"Extraction finished in {row['turns']} turns, {row['duration_s']} s · tokens: "
        f"{row['input_tokens'] + row['cache_read_tokens'] + row['cache_creation_tokens']:,} in / "
        f"{row['output_tokens']:,} out · equivalent cost ≈ USD {row['cost_usd']:.3f}")

    if data is None:
        try:
            data = json.loads(result.get("result", ""))
        except json.JSONDecodeError as e:
            raise ExtractionError("Claude's answer is not valid JSON.") from e
    try:
        component = Component.model_validate(data)
    except ValidationError as e:
        raise ExtractionError(f"The JSON does not match the schema: {e}") from e
    component.part_number = component.part_number or part_number
    return component
