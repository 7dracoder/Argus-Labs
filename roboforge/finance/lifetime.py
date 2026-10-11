"""Lifetime economics (TCO) and business return (payback / ROI)."""
from __future__ import annotations

from pydantic import BaseModel, Field

from roboforge.finance.bom import BOM
from roboforge.models import Component


class TCOInput(BaseModel):
    model_config = {"allow_inf_nan": False}
    years: float = Field(default=3, gt=0)
    hours_per_day: float = Field(default=2, ge=0, le=24)
    duty_cycle: float = Field(default=0.5, ge=0, le=1, description="Avg fraction of peak power drawn")
    electricity_usd_per_kwh: float = Field(default=0.17, ge=0)
    maintenance_pct_per_year: float = Field(default=8, ge=0, description="% of hardware cost per year")
    tasks_per_day: float = Field(default=0, ge=0)
    annual_savings_usd: float | None = Field(default=None, ge=0, description="For commercial ROI")


class TCOReport(BaseModel):
    hardware_usd: float
    peak_power_w: float
    energy_kwh_total: float
    energy_usd: float
    maintenance_usd: float
    total_cost_of_ownership_usd: float
    cost_per_operating_hour_usd: float | None
    cost_per_task_usd: float | None
    payback_years: float | None
    roi_pct: float | None
    assumptions: dict


def peak_power_w(components: list[Component]) -> float:
    return sum(c.specs.get("power_w", 0.0) * c.quantity for c in components)


def estimate_tco(components: list[Component], bom: BOM, params: TCOInput) -> TCOReport:
    peak = peak_power_w(components)
    hours = params.hours_per_day * 365 * params.years
    kwh = peak * params.duty_cycle * hours / 1000
    energy = kwh * params.electricity_usd_per_kwh
    maintenance = bom.total_usd * params.maintenance_pct_per_year / 100 * params.years
    tco = bom.total_usd + energy + maintenance

    tasks = params.tasks_per_day * 365 * params.years
    payback = roi = None
    if params.annual_savings_usd is not None:
        annual_running = (energy + maintenance) / params.years
        net_annual = params.annual_savings_usd - annual_running
        payback = round(bom.total_usd / net_annual, 2) if net_annual > 0 else None
        roi = round((params.annual_savings_usd * params.years - tco) / tco * 100, 1) if tco > 0 else None

    return TCOReport(
        hardware_usd=bom.total_usd,
        peak_power_w=round(peak, 1),
        energy_kwh_total=round(kwh, 2),
        energy_usd=round(energy, 2),
        maintenance_usd=round(maintenance, 2),
        total_cost_of_ownership_usd=round(tco, 2),
        cost_per_operating_hour_usd=round(tco / hours, 2) if hours else None,
        cost_per_task_usd=round(tco / tasks, 2) if tasks else None,
        payback_years=payback,
        roi_pct=roi,
        assumptions=params.model_dump(),
    )
