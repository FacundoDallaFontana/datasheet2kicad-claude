"""Contract between the AI extraction and the symbol/footprint generators.

All dimensions are in millimeters.
"""
from __future__ import annotations

import copy
from typing import Literal, Optional

from pydantic import BaseModel, Field

PinType = Literal[
    "input", "output", "bidirectional", "tri_state", "passive", "free",
    "unspecified", "power_in", "power_out", "open_collector", "open_emitter",
    "no_connect",
]
PinStyle = Literal[
    "line", "inverted", "clock", "inverted_clock", "input_low", "clock_low",
    "output_low", "edge_clock_high", "non_logic",
]
Side = Literal["left", "right", "top", "bottom"]
Confidence = Literal["high", "medium", "low"]
Family = Literal["gullwing", "nolead", "tab", "other"]


class Dim(BaseModel):
    """A toleranced dimension as it appears in the datasheet table."""
    min: Optional[float] = None
    nom: Optional[float] = None
    max: Optional[float] = None

    def has_value(self) -> bool:
        return any(v is not None for v in (self.min, self.nom, self.max))

    def nominal(self) -> Optional[float]:
        if self.nom is not None:
            return self.nom
        if self.min is not None and self.max is not None:
            return (self.min + self.max) / 2
        return self.min if self.min is not None else self.max

    def lo(self) -> Optional[float]:
        return self.min if self.min is not None else self.nominal()

    def hi(self) -> Optional[float]:
        return self.max if self.max is not None else self.nominal()


class Pin(BaseModel):
    number: str = Field(description="Pin/pad number as in the pinout (EP included).")
    name: str = Field(description="Pin name; use ~{X} for active-low signals.")
    type: PinType
    side: Side = Field(description="Side of the symbol where the pin goes.")
    unit: int = Field(1, description="Symbol unit (1 unless it is a multi-unit part).")
    style: PinStyle = "line"
    hidden: bool = False
    description: str = ""


class ExposedPad(BaseModel):
    number: str = Field(description="Pin number assigned to the EP/thermal pad.")
    x: Dim
    y: Dim


class Tab(BaseModel):
    """Heatsink tab of SOT-223 / TO-252 / TO-263."""
    number: str = Field(description="Pin number of the tab.")
    width: Dim = Field(description="Tab width (along the pin axis).")
    length: Dim = Field(description="Length of the exposed tab metal measured from the outer edge.")


class Package(BaseModel):
    family: Family = Field(description="gullwing: SOIC/SSOP/TSSOP/QFP/SOT-23; nolead: QFN/DFN/SON; "
                                       "tab: SOT-223/TO-252/TO-263; other: not supported.")
    name: str = Field(description="Package name in the datasheet, e.g. 'VQFN-16 (RGT)'.")
    jedec: Optional[str] = Field(None, description="JEDEC reference if given (MO-220, MS-012...).")
    pin_count: int = Field(description="Number of physical terminals, excluding EP and tab.")
    pitch: Optional[float] = None
    num_pins_x: int = Field(0, description="Pins on each horizontal row (top/bottom). 0 for dual packages.")
    num_pins_y: int = Field(0, description="Pins on each vertical column (left/right).")
    deleted_pins: list[int] = Field(default_factory=list,
                                    description="Empty grid positions (e.g. SOT-23-5 → [5]).")
    body_x: Dim = Field(description="Body width perpendicular to the dual pin rows (E1).")
    body_y: Dim = Field(description="Body length (D).")
    overall_x: Dim = Field(default_factory=Dim, description="Lead tip to lead tip in X (E). Gullwing/tab.")
    overall_y: Dim = Field(default_factory=Dim, description="Tip to tip in Y (total D). QFP only.")
    body_height: Dim = Field(default_factory=Dim, description="Total height (A).")
    lead_width: Dim = Field(description="Terminal width (b).")
    lead_len: Dim = Field(description="Length of the foot/terminal touching the PCB (L).")
    ep: Optional[ExposedPad] = None
    tab: Optional[Tab] = None
    confidence: Confidence = "medium"
    source_pages: list[int] = Field(default_factory=list)


class SourcePages(BaseModel):
    ordering: list[int] = Field(default_factory=list)
    pinout: list[int] = Field(default_factory=list)
    package: list[int] = Field(default_factory=list)


class Component(BaseModel):
    status: Literal["ok", "part_not_found", "ambiguous"]
    part_number: str = Field(description="Full orderable part number requested by the user.")
    symbol_name: str = Field("", description="Symbol name (part number without the packaging suffix).")
    manufacturer: str = ""
    description: str = ""
    keywords: str = ""
    datasheet_url: str = ""
    reference: str = Field("U", description="Reference prefix: U, Q, D...")
    candidates: list[str] = Field(default_factory=list,
                                  description="If status != ok: similar orderable part numbers that exist.")
    pins: list[Pin] = Field(default_factory=list)
    pins_confidence: Confidence = "medium"
    package: Optional[Package] = None
    source_pages: SourcePages = Field(default_factory=SourcePages)
    notes: list[str] = Field(default_factory=list)


def _inline_refs(node, defs):
    if isinstance(node, dict):
        if "$ref" in node:
            target = defs[node["$ref"].split("/")[-1]]
            merged = {**_inline_refs(copy.deepcopy(target), defs),
                      **{k: v for k, v in node.items() if k != "$ref"}}
            return merged
        return {k: _inline_refs(v, defs) for k, v in node.items() if k != "$defs"}
    if isinstance(node, list):
        return [_inline_refs(v, defs) for v in node]
    return node


def component_json_schema() -> dict:
    """Self-contained JSON Schema (no $ref) to pass to `claude --json-schema`."""
    schema = Component.model_json_schema()
    return _inline_refs(schema, schema.get("$defs", {}))
