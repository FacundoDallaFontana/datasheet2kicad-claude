"""Contrato entre la extracción con IA y los generadores de símbolo/footprint.

Todas las dimensiones están en milímetros.
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
    """Dimensión con tolerancia tal como aparece en la tabla del datasheet."""
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
    number: str = Field(description="Número de pin/pad tal como en el pinout (EP incluido).")
    name: str = Field(description="Nombre del pin; usar ~{X} para señales activas en bajo.")
    type: PinType
    side: Side = Field(description="Lado del símbolo donde va el pin.")
    unit: int = Field(1, description="Unidad del símbolo (1 salvo partes multi-unidad).")
    style: PinStyle = "line"
    hidden: bool = False
    description: str = ""


class ExposedPad(BaseModel):
    number: str = Field(description="Número de pin asignado al EP/thermal pad.")
    x: Dim
    y: Dim


class Tab(BaseModel):
    """Tab de disipación de SOT-223 / TO-252 / TO-263."""
    number: str = Field(description="Número de pin del tab.")
    width: Dim = Field(description="Ancho del tab (a lo largo del eje de los pines).")
    length: Dim = Field(description="Largo del metal expuesto del tab medido desde el borde exterior.")


class Package(BaseModel):
    family: Family = Field(description="gullwing: SOIC/SSOP/TSSOP/QFP/SOT-23; nolead: QFN/DFN/SON; "
                                       "tab: SOT-223/TO-252/TO-263; other: no soportado.")
    name: str = Field(description="Nombre del package en el datasheet, p.ej. 'VQFN-16 (RGT)'.")
    jedec: Optional[str] = Field(None, description="Referencia JEDEC si aparece (MO-220, MS-012...).")
    pin_count: int = Field(description="Cantidad de terminales físicos, sin contar EP ni tab.")
    pitch: Optional[float] = None
    num_pins_x: int = Field(0, description="Pines en cada fila horizontal (arriba/abajo). 0 en packages duales.")
    num_pins_y: int = Field(0, description="Pines en cada columna vertical (izq./der.).")
    deleted_pins: list[int] = Field(default_factory=list,
                                    description="Posiciones vacías de la grilla (p.ej. SOT-23-5 → [5]).")
    body_x: Dim = Field(description="Ancho del cuerpo perpendicular a las filas de pines duales (E1).")
    body_y: Dim = Field(description="Largo del cuerpo (D).")
    overall_x: Dim = Field(default_factory=Dim, description="Punta a punta de terminales en X (E). Gullwing/tab.")
    overall_y: Dim = Field(default_factory=Dim, description="Punta a punta en Y (D total). Solo QFP.")
    body_height: Dim = Field(default_factory=Dim, description="Altura total (A).")
    lead_width: Dim = Field(description="Ancho del terminal (b).")
    lead_len: Dim = Field(description="Largo del pie/terminal que toca el PCB (L).")
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
    part_number: str = Field(description="Código de pedido completo pedido por el usuario.")
    symbol_name: str = Field("", description="Nombre del símbolo (código sin sufijo de embalaje).")
    manufacturer: str = ""
    description: str = ""
    keywords: str = ""
    datasheet_url: str = ""
    reference: str = Field("U", description="Prefijo de referencia: U, Q, D...")
    candidates: list[str] = Field(default_factory=list,
                                  description="Si status != ok: códigos de pedido existentes parecidos.")
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
    """JSON Schema autocontenido (sin $ref) para pasarle a `claude --json-schema`."""
    schema = Component.model_json_schema()
    return _inline_refs(schema, schema.get("$defs", {}))
