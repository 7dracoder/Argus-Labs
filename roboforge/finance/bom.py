"""Bill of materials: itemized lines, per-category subtotals, totals."""
from __future__ import annotations

from pydantic import BaseModel

from roboforge.models import Component


class BOMLine(BaseModel):
    component_id: str
    name: str
    category: str
    kind: str
    source: str
    quantity: int
    unit_cost_usd: float
    line_total_usd: float
    supplier: str | None
    lead_time_days: int | None


class BOM(BaseModel):
    lines: list[BOMLine]
    by_category_usd: dict[str, float]
    total_usd: float
    total_mass_kg: float
    max_lead_time_days: int | None
    disclaimer: str = "Estimates from catalog placeholder prices; excludes shipping, tax and labor."


def build_bom(components: list[Component]) -> BOM:
    lines: list[BOMLine] = []
    by_category: dict[str, float] = {}
    mass = 0.0
    lead_times: list[int] = []

    for c in components:
        line_total = round(c.unit_cost_usd * c.quantity, 2)
        lines.append(BOMLine(
            component_id=c.id, name=c.name, category=c.category.value, kind=c.kind, source=c.source,
            quantity=c.quantity, unit_cost_usd=c.unit_cost_usd, line_total_usd=line_total,
            supplier=c.supplier, lead_time_days=c.lead_time_days,
        ))
        by_category[c.category.value] = round(by_category.get(c.category.value, 0.0) + line_total, 2)
        mass += c.specs.get("mass_kg", 0.0) * c.quantity
        if c.lead_time_days is not None:
            lead_times.append(c.lead_time_days)

    return BOM(
        lines=lines,
        by_category_usd=by_category,
        total_usd=round(sum(l.line_total_usd for l in lines), 2),
        total_mass_kg=round(mass, 3),
        max_lead_time_days=max(lead_times) if lead_times else None,
    )
