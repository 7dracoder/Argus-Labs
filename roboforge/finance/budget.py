"""Budget check against user budget, including a contingency reserve."""
from __future__ import annotations

from pydantic import BaseModel

from roboforge.finance.bom import BOM


class BudgetReport(BaseModel):
    budget_usd: float | None
    bom_total_usd: float
    contingency_pct: float
    contingency_usd: float
    projected_total_usd: float
    remaining_usd: float | None
    status: str  # "no_budget" | "within_budget" | "over_budget"
    largest_cost_drivers: list[dict]


def check_budget(bom: BOM, budget_usd: float | None, contingency_pct: float = 10.0) -> BudgetReport:
    contingency = round(bom.total_usd * contingency_pct / 100, 2)
    projected = round(bom.total_usd + contingency, 2)
    drivers = sorted(bom.lines, key=lambda l: l.line_total_usd, reverse=True)[:3]

    if budget_usd is None:
        status, remaining = "no_budget", None
    else:
        remaining = round(budget_usd - projected, 2)
        status = "within_budget" if remaining >= 0 else "over_budget"

    return BudgetReport(
        budget_usd=budget_usd,
        bom_total_usd=bom.total_usd,
        contingency_pct=contingency_pct,
        contingency_usd=contingency,
        projected_total_usd=projected,
        remaining_usd=remaining,
        status=status,
        largest_cost_drivers=[{"name": d.name, "line_total_usd": d.line_total_usd} for d in drivers],
    )
