"""One part, up close: what it holds, how hard it's working, and plain-language edits.

`info()` feeds the part inspector under the 3D view. `edit()` turns an instruction
such as "make it cheaper", "stronger", "use the Maxon" or "remove it" into a
catalog swap or removal, with the same sizing rules the configurator uses.
Loads are screening estimates, not verified engineering.
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from roboforge.assembly import _infer_archetype
from roboforge.catalog import BODY_FIT, CATALOG, make_component
from roboforge.design import (ARM_REACH_M, ARM_SELF_MASS_KG, G, ROLLING_COEFF, SAFETY, _battery_need, _performance,
                              _tier)
from roboforge.finance import build_bom
from roboforge.models import Component, RobotProject, ValidationRecord

SPEC_LABELS = {
    "torque_nm": ("Torque", "N·m"), "max_load_kg": ("Rated load", "kg"), "max_payload_kg": ("Grip rating", "kg"),
    "capacity_wh": ("Energy", "Wh"), "power_w": ("Power draw", "W"), "mass_kg": ("Weight", "kg"),
    "diameter_mm": ("Diameter", "mm"), "volume_l": ("Volume", "L"), "diagonal_in": ("Screen", "in"),
    "range_m": ("Range", "m"), "compute_score": ("AI compute", "/ 5"), "quality": ("Quality", "/ 5"),
}
KEY_SPEC = {"frame": "max_load_kg", "drive_motor": "torque_nm", "arm_servo": "torque_nm", "battery": "capacity_wh",
            "wheel": "max_load_kg", "track": "max_load_kg", "gripper": "max_payload_kg", "lift": "max_load_kg",
            "cargo_bin": "volume_l", "compute": "compute_score", "lidar": "range_m", "display": "diagonal_in"}
ROLES = {
    "frame": "The robot's body. Every other part bolts to it, and it carries the weight of the robot and its load.",
    "drive_motor": "Turns the wheels or tracks so the robot can drive, climb slopes and stop under control.",
    "wheel": "Puts the robot on the ground. Its size sets how well it rolls over bumps and how fast it goes.",
    "track": "Rubber tracks spread the robot's weight so it can cross grass, gravel and rough ground.",
    "battery": "Stores the energy for every motor, sensor and computer. Its capacity sets how long the robot runs.",
    "compute": "The robot's brain. It runs navigation and vision and tells every motor what to do.",
    "camera": "The robot's eyes. It sees people, objects and obstacles, and measures how far away they are.",
    "lidar": "Spins a laser to map the room in 360° so the robot knows where it is and avoids walls.",
    "pan_tilt": "A motorised neck that aims the camera left, right, up and down without turning the robot.",
    "arm_servo": "A joint motor in the arm. Together the joints reach out and lift whatever the gripper holds.",
    "gripper": "The hand at the end of the arm. It closes around objects to pick them up and set them down.",
    "lift": "Raises and lowers the top deck to pick up shelves, totes or carts.",
    "cargo_bin": "The storage box that holds what the robot carries.",
    "display": "A screen that shows a face, video calls or status to people nearby.",
    "speaker": "Lets the robot talk, give warnings and play calls.",
    "microphone": "Hears voice commands and lets people talk through the robot.",
    "lights": "Lights the way at night and shows people what the robot is doing.",
    "proximity": "Short-range sensors that stop the robot before it bumps into or falls off something.",
    "vacuum": "Suction that pulls dust and debris into the robot's bin.",
    "side_brush": "A spinning brush that sweeps dirt from edges and corners into the vacuum's path.",
    "wiring": "Cables, connectors and fuses that carry power and signals between every part.",
    "arm_link": "A printed link that forms the arm's bones between its joint motors.",
    "chassis_plate": "A printed plate on top of the base where modules and payload mount.",
    "motor_bracket": "A printed bracket that holds a drive motor firmly to the frame.",
    "cover": "A printed shell screwed over the battery or computer so nothing is exposed; vents let heat out "
             "and a rear notch lets the cables through.",
}
KIND_ALIASES = {"frame": {"frame", "chassis", "base", "body"}, "speaker": {"speaker", "speakers"},
                "lights": {"lights", "light"}, "camera": {"camera", "cameras"}}
CONTROLLED = ("camera", "lidar", "microphone", "display", "speaker", "pan_tilt", "proximity", "drive_motor",
              "arm_servo", "lift", "vacuum", "gripper")

REMOVE_WORDS = ("remove", "delete", "get rid", "take it off", "take this off", "take it out", "drop it",
                "don't need", "dont need", "no need for", "without it")
CHEAPEST_WORDS = ("cheapest", "lowest price", "least expensive", "as cheap as")
CHEAPER_WORDS = ("cheaper", "cheap", "save", "less expensive", "lower cost", "budget", "cost less", "downgrade")
BEST_WORDS = ("best", "top of the line", "top-end", "maximum", "the most powerful", "highest")
STRONGER_WORDS = ("stronger", "bigger", "more", "longer", "powerful", "larger", "higher", "heavier", "faster",
                  "tougher", "sturdier", "beefier")
BETTER_WORDS = ("better", "upgrade", "premium", "nicer", "quality", "improve", "quieter", "smoother")
LIGHTER_WORDS = ("lighter", "less weight", "weigh less", "smaller", "slimmer")
FORCE_WORDS = ("anyway", "regardless", "even if", "don't care", "dont care")
ESSENTIAL = {"drive_motor": "drive", "wheel": "drive", "track": "drive", "battery": "run on battery",
             "compute": "think or control anything", "wiring": "be wired up"}
GENERIC_TOKENS = {"the", "and", "with", "kit", "for", "set", "pro", "gear", "motor", "gearmotor", "camera", "battery",
                  "frame", "chassis", "wheel", "wheels", "servo", "arm", "array", "light", "lights", "bar", "unit",
                  "head", "module", "sensor", "robot", "body", "shell", "plate", "base", "mm", "in"}


def _archetype(project: RobotProject) -> str:
    return (project.architecture or {}).get("archetype") or _infer_archetype(project.components)


def _fits(cid: str, archetype: str) -> bool:
    return archetype in BODY_FIT.get(cid, frozenset({archetype}))


def _find(project: RobotProject, component_id: str) -> Component:
    for c in project.components:
        if c.id == component_id:
            return c
    raise KeyError("Part not found in this revision.")


def _specs(specs: dict) -> list[dict]:
    return [{"key": k, "label": SPEC_LABELS[k][0], "value": round(v, 2), "unit": SPEC_LABELS[k][1]}
            for k, v in specs.items() if k in SPEC_LABELS and k != "depth"]


# ---------------------------------------------------------------- loads
def _demand(project: RobotProject, c: Component, specs: dict | None = None) -> dict | None:
    """How much of its rating this part (or a candidate with `specs`) would use in this robot."""
    specs = specs if specs is not None else c.specs
    comps = project.components
    payload = project.requirements.payload_kg or 0.0
    total = build_bom(comps).total_mass_kg - c.specs.get("mass_kg", 0) * c.quantity \
        + specs.get("mass_kg", 0) * c.quantity
    archetype = _archetype(project)
    need = label = None
    if c.kind == "frame":
        rolling = sum(x.specs.get("mass_kg", 0) * x.quantity for x in comps if x.kind in ("wheel", "track"))
        need, label = total - specs.get("mass_kg", 0) - rolling + payload, "Weight on the frame (parts + payload)"
    elif c.kind == "wheel":
        need, label = (total + payload) / max(c.quantity, 1) * 1.5, "Load per wheel (1.5× for bumps)"
    elif c.kind == "track":
        need, label = total + payload, "Robot weight on the tracks"
    elif c.kind == "drive_motor":
        track = any(x.kind == "track" for x in comps)
        wheel = next((x for x in comps if x.kind == "wheel"), None)
        radius = 0.045 if track else (wheel.specs.get("diameter_mm", 100) / 2000 if wheel else 0.05)
        coeff = 0.6 if track else ROLLING_COEFF
        need = (total + payload) * G * radius * coeff * SAFETY / max(c.quantity, 1)
        label = f"Torque needed per motor ({SAFETY:g}× safety)"
    elif c.kind == "arm_servo":
        reach = 0.28 if archetype == "stationary_arm" else ARM_REACH_M
        full = (payload + ARM_SELF_MASS_KG) * G * reach
        servos = [x for x in comps if x.kind == "arm_servo"]
        shoulder = max(servos, key=lambda x: x.specs.get("torque_nm", 0))
        is_shoulder = len(servos) == 1 or c.id == shoulder.id
        need = full if is_shoulder else full * 0.35
        label = "Shoulder torque needed" if is_shoulder else "Wrist torque needed"
    elif c.kind == "gripper":
        need, label = payload, "Heaviest object to grip"
    elif c.kind == "lift":
        need, label = max(payload, 10), "Load on the lift"
    elif c.kind == "battery":
        runtime = project.requirements.runtime_hours or 2
        trial = [x if x.id != c.id else x.model_copy(update={"specs": specs}) for x in comps]
        need, label = _battery_need(trial, runtime), f"Energy for {runtime:g} h (80% usable)"
    key = KEY_SPEC.get(c.kind)
    if need is None or not key or not specs.get(key):
        return None
    have = specs[key]
    pct = round(100 * need / have) if have else 999
    return {"label": label, "need": round(need, 2), "have": round(have, 2), "unit": SPEC_LABELS[key][1],
            "pct": pct, "status": "over" if need > have else "tight" if pct >= 85 else "ok"}


def _relations(project: RobotProject, c: Component) -> tuple[str, list[Component], Component | None]:
    others = [x for x in project.components if x.id != c.id]
    kinds = lambda *ks: [x for x in others if x.kind in ks]  # noqa: E731
    frame = next((x for x in others if x.kind == "frame"), None)
    verb, holds, mounted = "Holds", [], frame
    if c.kind == "frame":
        holds, mounted = [x for x in others if x.kind != "wiring"], None
    elif c.kind == "drive_motor":
        verb, holds = "Drives", kinds("wheel", "track")
    elif c.kind == "pan_tilt":
        verb, holds = "Points", kinds("camera")
    elif c.kind == "arm_servo":
        holds = kinds("gripper") + [x for x in kinds("arm_servo")
                                    if x.specs.get("torque_nm", 0) < c.specs.get("torque_nm", 0)]
    elif c.kind == "battery":
        verb, holds = "Powers", [x for x in others if x.specs.get("power_w")]
    elif c.kind == "compute":
        verb, holds = "Controls", kinds(*CONTROLLED)
    elif c.kind == "wiring":
        verb, holds = "Connects", [x for x in others if x.specs.get("power_w")]
    if c.kind == "camera":
        mounted = next(iter(kinds("pan_tilt")), frame)
    elif c.kind == "gripper":
        mounted = max(kinds("arm_servo"), key=lambda x: -x.specs.get("torque_nm", 0), default=frame)
    elif c.kind == "wheel":
        mounted = next(iter(kinds("drive_motor")), frame)
    return verb, holds, mounted


def _cargo(project: RobotProject, c: Component) -> str | None:
    payload = project.requirements.payload_kg
    if c.kind in ("frame", "gripper", "lift", "cargo_bin", "track") and payload:
        return f"Your payload: {payload:g} kg"
    if c.kind in ("wheel", "track", "drive_motor"):
        return "The whole robot and its payload"
    return None


def _alternatives(project: RobotProject, c: Component) -> list[dict]:
    if not c.catalog_id:
        return []
    archetype = _archetype(project)
    key = KEY_SPEC.get(c.kind)
    out = []
    for cid, item in CATALOG.items():
        if item["kind"] != c.kind or cid == c.catalog_id or not _fits(cid, archetype):
            continue
        demand = _demand(project, c, item["specs"])
        out.append({"catalog_id": cid, "name": item["name"], "unit_cost_usd": item["unit_cost_usd"],
                    "delta_usd": round((item["unit_cost_usd"] - c.unit_cost_usd) * c.quantity, 2),
                    "quality": item["specs"].get("quality", 3),
                    "key_spec": {"label": SPEC_LABELS[key][0], "value": item["specs"][key], "unit": SPEC_LABELS[key][1]}
                    if key and key in item["specs"] else None,
                    "meets": None if demand is None else demand["status"] != "over"})
    return sorted(out, key=lambda a: a["unit_cost_usd"])


def _explain(project: RobotProject, c: Component) -> dict:
    """What this part does, its job in this robot (from the concept) and why this exact part was picked."""
    decisions = (project.architecture or {}).get("decisions", [])
    names = KIND_ALIASES.get(c.kind, {c.kind})
    job = next((d["reason"] for d in decisions if d.get("part") == "Design"
                and names & set(re.findall(r"[a-z_]+", d.get("choice", "").lower()))), None)
    picked = next((d for d in reversed(decisions)
                   if d.get("choice", "").endswith((f"× {c.name}", f"→ {c.name}"))), None)
    why = None if not picked else "You chose this part." if picked["part"] == "Your edit" \
        else f"Upgraded with spare budget: {picked['reason']}" if picked["part"] == "Upgrade" else picked["reason"]
    if c.source == "generated" and not why:
        why = "Custom part, 3D-printed to fit this robot."
    return {"does": ROLES.get(c.kind, f"A {c.kind.replace('_', ' ')} for this robot."), "job": job, "why": why}


def info(project: RobotProject, component_id: str) -> dict:
    c = _find(project, component_id)
    verb, holds, mounted = _relations(project, c)
    return {
        "component_id": c.id, "catalog_id": c.catalog_id, "name": c.name, "kind": c.kind,
        "category": c.category.value, "source": c.source, "quantity": c.quantity, "supplier": c.supplier,
        "unit_cost_usd": c.unit_cost_usd, "line_total_usd": round(c.unit_cost_usd * c.quantity, 2),
        "lead_time_days": c.lead_time_days, "specs": _specs(c.specs), "explain": _explain(project, c),
        "holds_verb": verb, "holds": [{"component_id": x.id, "name": x.name, "quantity": x.quantity} for x in holds],
        "carries": _cargo(project, c),
        "mounted_on": {"component_id": mounted.id, "name": mounted.name} if mounted else None,
        "load": _demand(project, c), "alternatives": _alternatives(project, c),
        "removable": c.kind != "frame",
    }


# ---------------------------------------------------------------- edits
class PartEdit(BaseModel):
    instruction: str | None = Field(default=None, max_length=500)
    catalog_id: str | None = Field(default=None, max_length=80)
    remove: bool = False


class EditChoice(BaseModel):
    action: Literal["swap", "remove", "none"]
    catalog_id: str | None = None
    reply: str


def _rank(a: dict) -> tuple:
    return a["quality"], (a["key_spec"] or {}).get("value", 0)


def _pick(project: RobotProject, c: Component, text: str) -> tuple[str, str | None, str]:
    """Deterministic intent: ('swap', id, why) | ('remove', None, why) | ('none', None, '')."""
    from roboforge.archetypes import has_any
    alts = _alternatives(project, c)
    if has_any(text, REMOVE_WORDS):
        return "remove", None, "removed as asked"
    own = set(re.findall(r"[a-z0-9]+", c.name.lower()))
    scored = []
    for a in alts:
        tokens = {t for t in re.findall(r"[a-z0-9]+", f"{a['name']} {a['catalog_id']}".lower())
                  if len(t) >= 2 and t not in GENERIC_TOKENS and t not in own}
        hits = sum(1 for t in tokens if re.search(rf"\b{re.escape(t)}\b", text))
        if hits:
            scored.append((hits, a))
    if scored:
        scored.sort(key=lambda s: -s[0])
        if len(scored) == 1 or scored[0][0] > scored[1][0]:
            return "swap", scored[0][1]["catalog_id"], "the part you named"
    force = has_any(text, FORCE_WORDS)
    viable = [a for a in alts if a["meets"] is not False or force]
    current = {"quality": c.specs.get("quality", 3), "key_spec": {"value": c.specs.get(KEY_SPEC.get(c.kind, ""), 0)}}
    cheapest, cheaper = has_any(text, CHEAPEST_WORDS), has_any(text, CHEAPER_WORDS)
    if cheapest or cheaper:
        pool = [a for a in viable if a["delta_usd"] < 0]
        if pool:
            pick = min(pool, key=lambda a: a["unit_cost_usd"]) if cheapest else max(pool, key=lambda a: a["unit_cost_usd"])
            return "swap", pick["catalog_id"], "cheapest option that still works" if cheapest else "next step down in price"
        weak = [a for a in alts if a["delta_usd"] < 0]
        if weak:
            w = min(weak, key=lambda a: a["unit_cost_usd"])
            return "none", None, (f"Every cheaper option is too weak for this robot (e.g. {w['name']}, "
                                  f"${-w['delta_usd']:,.0f} less). Say “cheaper anyway” to swap regardless.")
        return "none", None, "This is already the cheapest part of its type that fits this robot."
    if has_any(text, BEST_WORDS):
        top = max(alts, key=_rank, default=None)
        return ("swap", top["catalog_id"], "top of the catalog") if top and _rank(top) > _rank(current) \
            else ("none", None, "This is already the best part of its type for this robot.")
    if has_any(text, LIGHTER_WORDS):
        mass = c.specs.get("mass_kg", 0)
        pool = [a for a in viable if CATALOG[a["catalog_id"]]["specs"].get("mass_kg", 1e9) < mass]
        return ("swap", pool[0]["catalog_id"], "lighter and still strong enough") if pool \
            else ("none", None, "No lighter part of this type still meets this robot's needs.")
    if has_any(text, STRONGER_WORDS):
        pool = [a for a in alts if (a["key_spec"] or {}).get("value", 0) > current["key_spec"]["value"]]
        pool = [a for a in pool if a["meets"] is not False] or pool
        return ("swap", pool[0]["catalog_id"], "cheapest step up") if pool \
            else ("none", None, "This is already the strongest part of its type that fits this robot.")
    if has_any(text, BETTER_WORDS):
        pool = [a for a in alts if a["quality"] > current["quality"]]
        return ("swap", pool[0]["catalog_id"], "cheapest higher-quality option") if pool \
            else ("none", None, "This is already the highest-quality part of its type here.")
    return "none", None, ""


def _ask_model(project: RobotProject, c: Component, text: str) -> tuple[str, str | None, str]:
    from roboforge.llm import generate_structured
    options = "\n".join(f"- {a['catalog_id']}: {a['name']}, ${a['unit_cost_usd']:g}, quality {a['quality']}/5"
                        + (f", {a['key_spec']['label']} {a['key_spec']['value']:g} {a['key_spec']['unit']}"
                           if a["key_spec"] else "") + ("" if a["meets"] is not False else " (too weak here)")
                        for a in _alternatives(project, c))
    choice = generate_structured(
        "You edit ONE part of a robot design. Choose action swap (with a catalog_id from the options), remove, "
        "or none. Never invent ids. If the request can't be done with these options, use none and say what is "
        "possible in one short sentence. reply is one short, plain sentence to the user.",
        f"Robot: {project.requirements.description}\nPart: {c.name} ({c.kind}), ${c.unit_cost_usd:g}, "
        f"specs {c.specs}\nOptions:\n{options or '(none)'}\nUser: {text}", EditChoice)
    if choice.action == "swap" and choice.catalog_id not in {a["catalog_id"] for a in _alternatives(project, c)}:
        return "none", None, choice.reply
    return choice.action, choice.catalog_id, choice.reply


def _spec_change(old: dict, new: dict, kind: str) -> str:
    key = KEY_SPEC.get(kind)
    if not key or key not in old or key not in new or old[key] == new[key]:
        return ""
    label, unit = SPEC_LABELS[key]
    return f" {label} {old[key]:g} → {new[key]:g} {unit}."


def edit(project: RobotProject, component_id: str, body: PartEdit) -> tuple[RobotProject, dict]:
    """Apply one edit in place (caller saves the revision). Returns (project, outcome)."""
    c = _find(project, component_id)
    text = (body.instruction or "").strip().lower()
    if body.remove:
        action, cid, why = "remove", None, "removed"
    elif body.catalog_id:
        action, cid, why = "swap", body.catalog_id, "chosen in the part panel"
    else:
        action, cid, why = _pick(project, c, text)
        if action == "none" and not why and text:
            try:
                action, cid, why = _ask_model(project, c, text)
            except Exception:  # model unavailable or malformed: fall back to clear guidance
                action, why = "none", ""
    if action == "none":
        hint = "Try “make it cheaper”, “stronger”, “the best one”, “lighter”, a part name, or “remove it”."
        return project, {"changed": False, "reply": why or f"I couldn't map that to a change. {hint}", "warnings": []}

    if action == "remove":
        if c.kind == "frame":
            return project, {"changed": False, "warnings": [],
                             "reply": "Every robot needs its frame. Ask for a cheaper or stronger one instead."}
        project.components = [x for x in project.components if x.id != c.id]
        reply, decision = f"Removed {c.name} (−${c.unit_cost_usd * c.quantity:,.0f}).", f"Removed {c.name}"
        if c.kind in ESSENTIAL:
            reply += f" Without it the robot can't {ESSENTIAL[c.kind]}; rebuild or swap one back in."
        new = None
    else:
        if cid not in CATALOG or CATALOG[cid]["kind"] != c.kind:
            return project, {"changed": False, "warnings": [], "reply": "That part can't replace this one."}
        if not _fits(cid, _archetype(project)):
            return project, {"changed": False, "warnings": [],
                             "reply": f"{CATALOG[cid]['name']} isn't built for this kind of robot."}
        new = make_component(cid, c.quantity)
        new.id = c.id
        project.components = [new if x.id == c.id else x for x in project.components]
        delta = (new.unit_cost_usd - c.unit_cost_usd) * c.quantity
        reply = (f"Swapped {c.name} → {new.name} ({'+' if delta >= 0 else '−'}${abs(delta):,.0f}, {why})."
                 + _spec_change(c.specs, new.specs, c.kind))
        decision = f"{c.name} → {new.name}"

    warnings = []
    for part in project.components:
        demand = _demand(project, part)
        if demand and demand["status"] == "over":
            warnings.append(f"{part.name}: {demand['label'].lower()} is {demand['need']:g} {demand['unit']}, "
                            f"above its {demand['have']:g} {demand['unit']} rating.")
    if new is not None and (d := _demand(project, new)):
        reply += f" It now runs at {d['pct']}% of its rating." if d["status"] != "over" else \
            f" Careful: that's {d['pct']}% of its rating, too weak for this robot."
    moving = any(x.kind == "drive_motor" for x in project.components)
    performance = _performance(project.components, moving)
    arch = project.architecture
    arch.update({"performance": performance, "tier": _tier(performance), "edited": True, "edit_warnings": warnings,
                 "decisions": [*arch.get("decisions", []),
                               {"part": "Your edit", "choice": decision,
                                "reason": body.instruction or "Chosen in the part panel."}]})
    project.validation.append(ValidationRecord(check="manual_part_edit", status="pending",
                                               detail=f"{decision}: fit, mounting and sizing need review."))
    return project, {"changed": True, "reply": reply, "warnings": warnings,
                     "component_id": new.id if new else None}
