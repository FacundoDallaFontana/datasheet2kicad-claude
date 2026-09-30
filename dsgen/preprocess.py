"""Finds the relevant pages of the datasheet with PyMuPDF.

Cuts down what the agent has to read in long datasheets: we pass it the candidate
ordering / pinout / package pages as a hint.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf as fitz

KEYWORDS = {
    "ordering": [
        r"ordering information", r"order(ing)? code", r"package option addendum",
        r"device options", r"orderable (part|device)", r"part number(ing)?",
        r"device information", r"marking",
    ],
    "pinout": [
        r"pin configuration", r"pin functions?", r"pin description", r"pin assignments?",
        r"pinout", r"terminal functions?", r"pin (out|diagram)",
    ],
    "package": [
        r"package (information|outline|dimensions|drawing)", r"mechanical (data|drawing)",
        r"outline dimensions", r"physical dimensions", r"land pattern", r"recommended footprint",
        r"solder pad layout", r"dimensions in millimet", r"controlling dimension",
    ],
}

# Maximum number of pages suggested per section.
MAX_PAGES_PER_SECTION = 6


@dataclass
class PageHints:
    page_count: int
    sections: dict[str, list[int]] = field(default_factory=dict)  # 1-based
    part_hits: list[int] = field(default_factory=list)

    def all_pages(self) -> list[int]:
        pages = {p for ps in self.sections.values() for p in ps} | set(self.part_hits)
        return sorted(pages)

    def as_ranges(self) -> str:
        """Compacts [1,2,3,7,8] -> '1-3, 7-8'."""
        pages = self.all_pages()
        if not pages:
            return ""
        ranges, start, prev = [], pages[0], pages[0]
        for p in pages[1:]:
            if p == prev + 1:
                prev = p
                continue
            ranges.append(f"{start}-{prev}" if start != prev else str(start))
            start = prev = p
        ranges.append(f"{start}-{prev}" if start != prev else str(start))
        return ", ".join(ranges)


def _base_part(part_number: str) -> str:
    """Strips common packaging suffixes to search for the part number in the text."""
    return re.sub(r"(/?(TR|T|R|RL|RL7|G4|PBF|-?REEL7?))$", "", part_number.strip(), flags=re.I)


def find_relevant_pages(pdf_path: Path, part_number: str) -> PageHints:
    doc = fitz.open(pdf_path)
    hints = PageHints(page_count=doc.page_count)
    scores: dict[str, list[tuple[int, int]]] = {k: [] for k in KEYWORDS}
    base = _base_part(part_number).lower()

    for i, page in enumerate(doc):
        text = page.get_text().lower()
        for section, patterns in KEYWORDS.items():
            score = sum(len(re.findall(p, text)) for p in patterns)
            if score:
                scores[section].append((score, i + 1))
        if base and base in text:
            hints.part_hits.append(i + 1)
    doc.close()

    for section, hits in scores.items():
        best = sorted(hits, reverse=True)[:MAX_PAGES_PER_SECTION]
        pages = sorted(p for _, p in best)
        # The mechanical drawing usually follows the title page: include the next one too.
        if section == "package":
            pages = sorted({q for p in pages for q in (p, p + 1) if q <= hints.page_count})
        hints.sections[section] = pages
    # Pages with the exact part number are usually few and valuable (ordering).
    hints.part_hits = hints.part_hits[:MAX_PAGES_PER_SECTION]
    return hints
