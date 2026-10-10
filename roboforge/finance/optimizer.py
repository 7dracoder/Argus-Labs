"""Design-to-budget optimizer.

Proposes catalog substitutions that are cheaper and meet or exceed every critical
spec of the part they replace. Proposals are NOT verified designs: the
Verification Agent must still recheck torque, mass, power and geometry.
"""
from __future__ import annotations

from pydantic import BaseModel

from roboforge.catalog import CATALOG, CRITICAL_SPECS, make_component
from roboforge.models import Component


class Substitution(BaseModel):
    component_id: str
    from_name: str
    to_catalog_id: str
    to_name: str
    quantity: int
    savings_usd: float
    spec_changes: dict[str, dict[str, float | None]]


class OptimizationResult(BaseModel):
    before_total_usd: float
    after_total_usd: float
    savings_usd: float
    target_savings_usd: float | None
    target_met: bool | None
    substitutions: list[Substitution]
    verification_status: str = "pending"
    notes: list[str] = []


def _meets_critical_specs(current: Component, candidate: dict) -> bool:
    for spec in CRITICAL_SPECS.get(current.kind, []):
        required = current.specs.get(spec)
        if required is not None and candidate["specs"].get(spec, float("-inf")) < required:
            return False
    return True


def _best_substitute(c: Component) -> tuple[str, dict] | None:
    """Cheapest compatible catalog part that is cheaper than the current one."""
    options = [
        (cid, item) for cid, item in CATALOG.items()
        if item["kind"] == c.kind and cid != c.catalog_id
        and item["unit_cost_usd"] < c.unit_cost_usd and _meets_critical_specs(c, item)
    ]
    return min(options, key=lambda o: o[1]["unit_cost_usd"]) if options else None


def optimize_cost(components: list[Component], target_savings_usd: float | None = None
                  ) -> tuple[list[Component], OptimizationResult]:
    """Greedy: apply highest-savings substitutions until the target is reached.

    Returns the proposed component list and a summary. Input is not mutated.
    """
    before = round(sum(c.unit_cost_usd * c.quantity for c in components), 2)

    candidates: list[tuple[int, Substitution, Component]] = []
    for idx, c in enumerate(components):
        found = _best_substitute(c)
        if not found:
            continue
        cid, item = found
        new = make_component(cid, c.quantity)
        new.id = c.id  # keep identity so assembly/electrical links stay valid
        keys = set(c.specs) | set(item["specs"])
        candidates.append((idx, Substitution(
            component_id=c.id, from_name=c.name, to_catalog_id=cid, to_name=item["name"],
            quantity=c.quantity,
            savings_usd=round((c.unit_cost_usd - item["unit_cost_usd"]) * c.quantity, 2),
            spec_changes={k: {"from": c.specs.get(k), "to": item["specs"].get(k)}
                          for k in sorted(keys) if c.specs.get(k) != item["specs"].get(k)},
        ), new))

    candidates.sort(key=lambda t: t[1].savings_usd, reverse=True)

    proposed = [c.model_copy(deep=True) for c in components]
    applied: list[Substitution] = []
    saved = 0.0
    for idx, sub, new in candidates:
        if target_savings_usd is not None and saved >= target_savings_usd:
            break
        proposed[idx] = new
        applied.append(sub)
        saved = round(saved + sub.savings_usd, 2)

    notes = ["Substitutions preserve critical specs only; mass, power draw, mounting and "
             "control interfaces must be rechecked by the Verification Agent."]
    target_met = None if target_savings_usd is None else saved >= target_savings_usd
    if target_met is False:
        notes.append("Catalog substitutions alone cannot reach the target; consider design "
                     "changes (simpler mechanism, fewer DOF, different material) or a higher budget.")

    return proposed, OptimizationResult(
        before_total_usd=before,
        after_total_usd=round(before - saved, 2),
        savings_usd=saved,
        target_savings_usd=target_savings_usd,
        target_met=target_met,
        substitutions=applied,
        notes=notes,
    )
