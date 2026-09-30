"""Registro de consumo de cada extracción con Claude en ~/.dsgen/usage.csv."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

USAGE_FILE = Path.home() / ".dsgen" / "usage.csv"
FIELDS = ["timestamp", "pdf", "part_number", "model", "status", "attempt", "turns", "duration_s",
          "input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens", "cost_usd"]


def record(pdf: Path, part_number: str, model: str, attempt: int, result: dict, status: str) -> dict:
    """Agrega una fila a partir del evento `result` de `claude -p --output-format stream-json`."""
    u = result.get("usage") or {}
    row = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "pdf": pdf.name,
        "part_number": part_number,
        "model": model,
        "status": status,
        "attempt": attempt,
        "turns": result.get("num_turns", ""),
        "duration_s": round((result.get("duration_ms") or 0) / 1000, 1),
        "input_tokens": u.get("input_tokens", 0),
        "output_tokens": u.get("output_tokens", 0),
        "cache_read_tokens": u.get("cache_read_input_tokens", 0),
        "cache_creation_tokens": u.get("cache_creation_input_tokens", 0),
        "cost_usd": round(result.get("total_cost_usd") or 0, 4),
    }
    USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    new = not USAGE_FILE.exists()
    with USAGE_FILE.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)
    return row


@dataclass
class Summary:
    calls: int = 0
    parts: int = 0
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_tokens: int = 0
    seconds: float = 0.0

    def describe(self) -> str:
        if not self.calls:
            return "Sin extracciones registradas todavía."
        avg = self.cost_usd / self.parts if self.parts else 0
        return (f"{self.calls} llamadas a Claude, {self.parts} componentes distintos · "
                f"≈ USD {self.cost_usd:.2f} (promedio USD {avg:.3f}/componente) · "
                f"tokens: {self.input_tokens + self.cache_tokens:,} entrada / {self.output_tokens:,} salida · "
                f"{self.seconds / 60:.1f} min")


def summary() -> Summary:
    s = Summary()
    if not USAGE_FILE.exists():
        return s
    parts = set()
    with USAGE_FILE.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            s.calls += 1
            parts.add((row["pdf"], row["part_number"].upper()))
            s.cost_usd += float(row["cost_usd"] or 0)
            s.input_tokens += int(row["input_tokens"] or 0)
            s.output_tokens += int(row["output_tokens"] or 0)
            s.cache_tokens += int(row["cache_read_tokens"] or 0) + int(row["cache_creation_tokens"] or 0)
            s.seconds += float(row["duration_s"] or 0)
    s.parts = len(parts)
    return s
