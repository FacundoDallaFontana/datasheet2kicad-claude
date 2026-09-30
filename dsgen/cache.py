"""Caché de extracciones: evita volver a llamar a Claude para el mismo PDF + part number."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .schema import Component

CACHE_DIR = Path.home() / ".dsgen" / "cache"
# Subir cuando cambie prompts/extract_component.md o el schema: invalida la caché vieja.
PROMPT_VERSION = "1"


def _key(pdf_path: Path, part_number: str) -> str:
    h = hashlib.sha256(pdf_path.read_bytes()).hexdigest()[:16]
    return f"{h}_{part_number.strip().upper()}_v{PROMPT_VERSION}"


def load(pdf_path: Path, part_number: str) -> Component | None:
    path = CACHE_DIR / f"{_key(pdf_path, part_number)}.json"
    if not path.exists():
        return None
    try:
        return Component.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError:
        return None


def store(pdf_path: Path, part_number: str, component: Component) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{_key(pdf_path, part_number)}.json"
    path.write_text(json.dumps(component.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")
