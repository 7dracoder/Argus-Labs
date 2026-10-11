"""Deterministic robot configurator: requirements -> costed catalog build.

Picks the cheapest catalog part that meets each engineering need (torque,
battery energy, payload) and explains every choice. Numbers are screening
estimates for a prototype, not verified engineering.
"""
from __future__ import annotations

import re
from typing import Callable

from pydantic import BaseModel

from roboforge.archetypes import ARCHETYPES, ARM_WORDS, INDOOR_WORDS, OUTDOOR_WORDS, classify, has_any, has_word, \
    open_deck_modules
from roboforge.catalog import BODY_FIT, CATALOG, make_component
from roboforge.concept import Concept, to_archetype
from roboforge.finance import build_bom, check_budget, optimize_cost
from roboforge.models import Component, Requirements

G = 9.81
ARM_REACH_M = 0.20       # assumed horizontal reach at full extension
ARM_SELF_MASS_KG = 0.35  # links + wrist hardware carried by the shoulder
WHEEL_RADIUS_M = 0.06
ROLLING_COEFF = 0.3      # rolling resistance + gentle acceleration / thresholds
SAFETY = 2.0

FIXED_WORDS = ("desk", "stationary", "fixed", "bench", "tabletop", "table-top", "mounted")
LEGGED_WORDS = ("stairs", "upstairs", "downstairs", "legs", "legged", "walk", "humanoid", "quadruped", "biped",
                "robot dog", "robotic dog")
VOICE_WORDS = ("voice", "speak", "talk", "listen", "command")

# Ground robots only: briefs that need flight, swimming or wall climbing are refused, not faked.
UNSUPPORTED = (
    (("fly", "flies", "flying", "drone", "quadcopter", "airborne", "hover"), None,
     "Flying robots aren't supported. Argus designs ground robots: wheels, tracks or a bench-mounted arm."),
    (("underwater", "swim", "submarine", "aquarium", "boat", "pool"), None,
     "Robots that work in water need waterproof hulls and thrusters, which aren't in the catalog. "
     "Argus designs ground robots only."),
    (("window", "facade", "glass wall"), ("clean", "wash", "wipe"),
     "Window-cleaning robots cling to glass with suction, which isn't supported. Argus designs ground robots only."),
    (("climb walls", "climbs walls", "wall climbing", "wall-climbing"), None,
     "Wall-climbing robots aren't supported. Argus designs ground robots only."),
)
# Jobs whose tool isn't in the catalog: the base is designed, the tool is flagged instead of faked.
MISSING_TOOLS = (
    (("mow", "lawn", "grass"), "a cutting deck and blade motor"),
    (("water my", "water the", "waters my", "waters the", "watering", "irrigat"),
     "a water tank and pump"),
    (("mop",), "a water tank and mop pad (this design vacuums)"),
    (("cook", "chef"), "cooking tools and heat-safe utensils"),
    (("paint",), "a paint sprayer or brush holder"),
    (("mix drinks", "mixes drinks", "cocktail", "bartend", "pour"), "liquid dispensers and pumps"),
    (("dishes",), "a dish rack and water-safe gripper"),
)
BRIEF_WORDS = ("robot", "bot", "carry", "move", "help", "clean", "drive", "home", "work", "assist", "lift",
               "transport", "watch", "follow", "explore", "rover", "wheel", "track", "camera", "budget",
               "kg", "payload", "task", "job", "deliver", "pick", "vacuum", "arm", "sort")


class BriefError(ValueError):
    """The brief describes something Argus can't (or shouldn't pretend to) design."""


def brief_problem(req: Requirements) -> str | None:
    """Why this brief can't be designed, or None. Checks only what the user wrote."""
    text = " ".join([req.description, *req.tasks]).lower()  # environment defaults to "indoor"
    words = re.findall(r"[a-z]+", text)
    if not words:
        return "Describe what the robot should do, e.g. “carry 5 kg packages around my office”."
    for triggers, context, message in UNSUPPORTED:
        if has_any(text, triggers) and (context is None or has_any(text, context)):
            return message
    vocabulary = (*BRIEF_WORDS, *ARM_WORDS, *INDOOR_WORDS, *OUTDOOR_WORDS,
                  *(w for a in ARCHETYPES.values() for w in a.keywords))
    if len(words) < 6 and not has_any(text, vocabulary):
        return ("That doesn't describe a robot job yet. Say what it should do, where, and how much it carries, "
                "e.g. “a robot that picks up toys in my living room”.")
    return None


class Decision(BaseModel):
    part: str
    choice: str
    reason: str


class DesignResult(BaseModel):
    components: list[Component]
    robot_type: str
    archetype: str = "mobile_robot"
    decisions: list[Decision]
    warnings: list[str]
    assumptions: list[str]
    requirements: Requirements
    performance: int = 0  # 0-100 weighted part quality
    tier: str = "Basic"
    upgrades: list[str] = []
    next_upgrade: dict | None = None  # cheapest further upgrade if the budget grows
    concept: dict | None = None  # the AI concept this build was sized from


def _text(req: Requirements) -> str:
    return " ".join([req.description, *req.tasks, req.environment or "", req.mobility or ""]).lower()


def _cheapest(kind: str, spec: str | None = None, minimum: float = 0.0,
              archetype: str | None = None) -> tuple[str, bool]:
    """Cheapest part of `kind` with spec >= minimum. Falls back to the strongest (False)."""
    items = [(cid, i) for cid, i in CATALOG.items() if i["kind"] == kind
             and (archetype is None or _fits(cid, archetype))]
    ok = [(cid, i) for cid, i in items if spec is None or i["specs"].get(spec, 0) >= minimum]
    if ok:
        return min(ok, key=lambda t: t[1]["unit_cost_usd"])[0], True
    return max(items, key=lambda t: t[1]["specs"].get(spec, 0))[0], False


def _infer(req: Requirements) -> tuple[Requirements, list[str], list[str]]:
    text, assumptions, warnings = _text(req), [], []
    payload = req.payload_kg
    if payload is None:
        match = re.search(r"(\d+(?:\.\d+)?)\s*(kg|kilo)", text)
        payload = float(match.group(1)) if match else 1.0
        if not match:
            assumptions.append("Payload assumed to be 1 kg.")
    mobility = (req.mobility or "").lower()
    if not mobility:
        mobility = "fixed" if has_any(text, FIXED_WORDS) else "wheeled"
        assumptions.append(f"Mobility assumed: {mobility}.")
    if has_any(text, LEGGED_WORDS) or mobility in ("legged", "humanoid", "walking"):
        warnings.append("Legged and stair-climbing robots aren't supported yet; this design uses wheels "
                        "on one floor.")
        mobility = "wheeled"
    if mobility not in ("wheeled", "fixed"):
        mobility = "wheeled"
    runtime = req.runtime_hours
    if runtime is None and mobility == "wheeled":
        runtime = 2.0
        assumptions.append("Battery runtime target assumed to be 2 hours.")
    updated = req.model_copy(update={"payload_kg": payload, "mobility": mobility, "runtime_hours": runtime,
                                     "assumptions": list(dict.fromkeys([*req.assumptions, *assumptions]))})
    return updated, assumptions, warnings


WEIGHTS = {"arm_servo": 3, "compute": 3, "camera": 2.5, "lidar": 2.5, "drive_motor": 2, "battery": 2,
           "frame": 1.5, "gripper": 1.5, "microphone": 1, "vacuum": 2.5, "lift": 2, "track": 1.5,
           "display": 1.5, "pan_tilt": 1.5, "wheel": 1, "cargo_bin": 1}
UPGRADE_REASONS = {
    "arm_servo": "Stronger, more precise arm joints with position feedback.",
    "compute": "More on-board AI for vision, mapping and voice.",
    "camera": "Sharper, longer-range depth vision.",
    "lidar": "360° lidar for mapping and obstacle avoidance.",
    "drive_motor": "Smoother, quieter, longer-lasting drive.",
    "battery": "Longer runtime between charges.",
    "frame": "Stiffer metal frame with more load margin.",
    "gripper": "Metal servo gripper with a higher grip rating.",
    "microphone": "Adds voice commands.",
    "vacuum": "Stronger suction picks up more dirt per pass.",
    "lift": "Lifts heavier shelves and totes.",
    "track": "Metal tracks carry more and last longer on rough ground.",
    "display": "Bigger, sharper screen for video calls.",
    "pan_tilt": "Stabilised brushless camera head.",
    "wheel": "Better wheels: smoother ride, more load, or sideways driving.",
    "cargo_bin": "Bigger lockable metal cargo bin.",
}
ADDONS = {"lidar": "rplidar-a1", "microphone": "respeaker-array"}
# Body plans where a mic array is a sensible upgrade even if the brief didn't ask for voice.
VOICE_BODIES = ("mobile_manipulator", "mobile_robot", "telepresence", "stationary_arm")


def _fits(cid: str, archetype: str) -> bool:
    return archetype in BODY_FIT.get(cid, frozenset({archetype}))


def _quality(c: Component) -> float:
    return c.specs.get("quality", 3)


def _peak_w(build: list[Component]) -> float:
    return sum(c.specs.get("power_w", 0) * c.quantity for c in build)


MOTOR_KINDS = ("drive_motor", "lift", "vacuum")


def _average_w(build: list[Component]) -> float:
    """Typical draw: motors run ~20% of peak on average, electronics ~60%."""
    return 10 + sum(c.specs.get("power_w", 0) * c.quantity * (0.2 if c.kind in MOTOR_KINDS else 0.6) for c in build)


def _battery_need(build: list[Component], runtime: float | None) -> float:
    return _average_w(build) * (runtime or 2) / 0.8


def _powered_ok(build: list[Component], runtime: float | None, wheeled: bool) -> bool:
    battery = next((c for c in build if c.kind == "battery"), None)
    return not wheeled or battery is None or battery.specs.get("capacity_wh", 0) >= _battery_need(build, runtime)


def _performance(build: list[Component], wheeled: bool) -> int:
    kinds = {c.kind for c in build if c.kind in WEIGHTS} | ({"lidar"} if wheeled else set()) | {"microphone"}
    score = sum(WEIGHTS[k] * max((_quality(c) for c in build if c.kind == k), default=0) for k in kinds)
    return round(100 * score / (5 * sum(WEIGHTS[k] for k in kinds))) if kinds else 0


def _tier(performance: int) -> str:
    return "Pro" if performance >= 85 else "Advanced" if performance >= 70 else "Standard" if performance >= 52 else "Basic"


def _candidates(build, needs, light_ids, req, wheeled, archetype="mobile_robot"):
    """Every single-step upgrade or add-on: (trial build, quality gain, label)."""
    for index, c in enumerate(build):
        if c.kind not in WEIGHTS:
            continue
        for cid, item in CATALOG.items():
            if item["kind"] != c.kind or item["specs"].get("quality", 3) <= _quality(c):
                continue
            if item["specs"].get("omni") and (archetype != "warehouse_amr" or c.quantity != 4):
                continue  # mecanum wheels only make sense on a 4-wheel AMR
            if not _fits(cid, archetype):
                continue  # e.g. each body plan keeps a frame built for it
            if c.kind == "wheel" and not (ARCHETYPES[archetype].wheel_mm <= item["specs"]["diameter_mm"]
                                          <= ARCHETYPES[archetype].wheel_mm * 1.2):
                continue  # keep the wheel size that suits this body plan
            spec, minimum = needs.get(c.id, (None, 0))
            if spec and item["specs"].get(spec, 0) < minimum:
                continue
            new = make_component(cid, c.quantity)
            new.id = c.id
            trial = build[:index] + [new] + build[index + 1:]
            if _powered_ok(trial, req.runtime_hours, wheeled) or (
                    _battery_need(trial, req.runtime_hours) <= _battery_need(build, req.runtime_hours)):
                weight = WEIGHTS[c.kind] * (0.5 if c.id in light_ids else 1)
                yield trial, weight * (item["specs"].get("quality", 3) - _quality(c)), f"{c.name} → {item['name']}"
    present = {c.kind for c in build}
    for kind, cid in ADDONS.items():
        if kind in present or (kind == "lidar" and archetype == "stationary_arm") or (
                kind == "microphone" and archetype not in VOICE_BODIES):
            continue
        trial = [*build, make_component(cid, 1)]
        if _powered_ok(trial, req.runtime_hours, wheeled):
            yield trial, WEIGHTS[kind] * CATALOG[cid]["specs"]["quality"], f"Add {CATALOG[cid]['name']}"


def _spend_budget(build, needs, light_ids, req, wheeled, decisions, warnings, archetype="mobile_robot"):
    def projected(b):
        return check_budget(build_bom(b), req.budget_usd, req.contingency_pct).projected_total_usd

    budget = req.budget_usd
    if projected(build) > budget:
        proposed, result = optimize_cost(build, projected(build) - budget)
        if result.substitutions:
            build = proposed
            decisions.append(Decision(part="Budget", choice=f"Saved ${result.savings_usd:,.0f}",
                                      reason="Swapped to cheaper parts with equal or better specs."))
        light = next((c for c in build if c.id in light_ids and c.quantity > 2), None)
        if projected(build) > budget and light:
            light.quantity -= 1
            decisions.append(Decision(part="Budget", choice="4-joint arm",
                                      reason="Dropped the wrist-rotate joint to fit the budget."))
        if projected(build) > budget:
            warnings.append(f"Still ${projected(build) - budget:,.0f} over budget including contingency. "
                            "Raise the budget or simplify the brief.")
            minimum = {"kind": "minimum", "extra_usd": round(projected(build) - budget, 2),
                       "label": "Minimum build for this brief", "at_budget_usd": round(projected(build), 2)}
            return build, [], minimum
        return build, [], None

    upgrades: list[str] = []
    while True:
        base_cost = projected(build)
        best = None
        for trial, gain, label in _candidates(build, needs, light_ids, req, wheeled, archetype):
            cost = projected(trial)
            if cost <= budget and gain > 0:
                ratio = gain / max(cost - base_cost, 1.0)
                if best is None or ratio > best[0]:
                    best = (ratio, trial, label)
        if best is None:
            break
        build = best[1]
        upgrades.append(best[2])

    # What the next dollar would buy: the cheapest remaining upgrade.
    base_cost = projected(build)
    options = [(projected(t) - base_cost, label) for t, gain, label in _candidates(build, needs, light_ids, req, wheeled, archetype)]
    next_upgrade = None
    if options:
        extra, label = min(options)
        next_upgrade = {"extra_usd": round(extra, 2), "label": label, "at_budget_usd": round(base_cost + extra, 2)}
    return build, upgrades, next_upgrade


def _cheapest_where(kind: str, ok: Callable[[dict], bool]) -> str | None:
    items = [(cid, i) for cid, i in CATALOG.items() if i["kind"] == kind and ok(i)]
    return min(items, key=lambda t: t[1]["unit_cost_usd"])[0] if items else None


def configure(req: Requirements, concept: Concept | None = None) -> DesignResult:
    problem = brief_problem(req)
    if problem:
        raise BriefError(problem)
    req, assumptions, warnings = _infer(req)
    text = _text(req)
    if concept and concept.missing_tools:
        warnings.append(f"Not in the catalog, add yourself: {', '.join(concept.missing_tools[:4])}. "
                        "This design is the robot that carries them.")
    for triggers, tool in () if concept else MISSING_TOOLS:
        if has_any(text, triggers):
            warnings.append(f"The catalog doesn't include {tool}; this design is the robot that carries it. "
                            "Add the tool yourself.")
    if concept and "Payload assumed to be 1 kg." in assumptions:
        assumptions = [a for a in assumptions if a != "Payload assumed to be 1 kg."] + [
            f"Payload assumed: {concept.payload_kg:g} kg."]
        req = req.model_copy(update={"payload_kg": concept.payload_kg, "assumptions": [
            a for a in req.assumptions if a != "Payload assumed to be 1 kg."] + [
            f"Payload assumed: {concept.payload_kg:g} kg."]})
    payload = req.payload_kg or 0.0
    if concept:
        arch, why = to_archetype(concept), f"{concept.summary} Modelled on: {concept.reference}."
    else:
        arch, why = classify(text, payload, req.mobility, req.robot_type)
    moving = arch.wheels > 0 or arch.track
    if req.runtime_hours is None or ("Battery runtime target assumed to be 2 hours." in assumptions):
        if moving:
            req = req.model_copy(update={"runtime_hours": arch.runtime_h,
                                         "assumptions": [a for a in req.assumptions if "runtime" not in a]
                                         + [f"Runtime target assumed: {arch.runtime_h:g} h for a {arch.label.lower()}."]})
            assumptions = [a for a in assumptions if "runtime" not in a] + [f"Runtime assumed: {arch.runtime_h:g} h."]
    req = req.model_copy(update={"mobility": "wheeled" if moving else "fixed"})
    has_arm = arch.arm or (not concept and has_any(text, ARM_WORDS) and arch.key in ("tracked_explorer", "mobile_robot"))
    if has_arm and arch.key == "mobile_robot":
        arch = ARCHETYPES["mobile_manipulator"]
    voice = (concept.voice if concept else has_any(text, VOICE_WORDS)) or arch.key == "telepresence"
    build: list[Component] = []
    decisions: list[Decision] = [Decision(part="Body plan", choice=arch.label,
                                          reason=why if concept else f"{why} {arch.blurb}")]
    decisions += [Decision(part="Design", choice=r.part, reason=r.why) for r in (concept.reasons if concept else [])[:8]]

    needs: dict[str, tuple[str, float]] = {}  # component id -> (spec, minimum) it must keep
    light_ids: set[str] = set()

    def add(cid: str, qty: int, part: str, reason: str, need: tuple[str, float] | None = None) -> None:
        component = make_component(cid, qty)
        build.append(component)
        if need:
            needs[component.id] = need
        decisions.append(Decision(part=part, choice=f"{qty} × {CATALOG[cid]['name']}", reason=reason))

    # Frame: payload plus this body plan's own mass.
    load = payload + arch.base_mass_kg
    fitting = [cid for cid, i in CATALOG.items() if i["kind"] == "frame"
               and i["specs"]["max_load_kg"] >= load and _fits(cid, arch.key)]
    frame = min(fitting, key=lambda cid: CATALOG[cid]["unit_cost_usd"]) if fitting else None
    ok = frame is not None
    if not ok:
        frame, _ = _cheapest("frame", "max_load_kg", load)
        warnings.append(f"No {arch.label.lower()} frame in the catalog is rated for {load:.1f} kg.")
    add(frame, 1, "Frame", f"Cheapest {arch.label.lower()} frame rated for {load:.1f} kg "
                           f"(payload + ~{arch.base_mass_kg:g} kg robot).", ("max_load_kg", load))

    if has_arm:
        reach = 0.28 if arch.key == "stationary_arm" else ARM_REACH_M
        need = (payload + ARM_SELF_MASS_KG) * G * reach
        strong, ok = _cheapest("arm_servo", "torque_nm", need)
        light, _ = _cheapest("arm_servo", "torque_nm", need * 0.35)
        if strong == light:
            add(strong, 5, "Arm joints", f"5-joint arm; shoulder needs ≥{need:.1f} N·m at {reach * 100:.0f} cm reach.",
                ("torque_nm", need))
        else:
            add(strong, 2, "Shoulder + elbow", f"Need ≥{need:.1f} N·m holding {payload:g} kg at "
                                                f"{reach * 100:.0f} cm reach.", ("torque_nm", need))
            add(light, 3, "Base + wrist", f"Lighter joints need only ≥{need * 0.35:.1f} N·m.",
                ("torque_nm", need * 0.35))
            light_ids.add(build[-1].id)
        if not ok:
            warnings.append(f"No catalog servo gives {need:.1f} N·m. Reduce payload below "
                            f"{CATALOG[strong]['specs']['torque_nm'] / (G * reach) - ARM_SELF_MASS_KG:.1f} kg "
                            "or shorten the reach.")
        add("printed-parallel-gripper", 1, "Gripper", "Printed parallel gripper; cheapest end effector.",
            ("max_payload_kg", min(payload, 2.5)))
        if payload > CATALOG["printed-parallel-gripper"]["specs"]["max_payload_kg"]:
            warnings.append("Payload exceeds the printed gripper's 2.5 kg rating.")

    camera, _ = _cheapest("camera", "depth", 1)
    add(camera, 1, "Camera", "Cheapest depth camera; needed to find objects and obstacles.")
    vision_heavy = has_any(text, ("recogni", "detect", "navigate", "autonom", "map", "vision"))
    compute = "jetson-orin-nano" if vision_heavy else arch.compute
    add(compute, 1, "Computer", "Navigation and vision need on-board AI." if compute != "raspberry-pi-5"
        else "Raspberry Pi 5 is enough for this job; upgrade to Jetson for on-board AI vision.")
    if voice:
        add("respeaker-array", 1, "Microphone", "Voice interaction is part of this robot.")
    if arch.nav_lidar:
        add("rplidar-a1", 1, "Lidar", "Autonomous navigation needs a 360° lidar.")

    # Job-specific modules for this body plan.
    for kind in arch.modules:
        if kind == "cargo_bin":
            litres = 30 if has_any(text, ("large", "big", "bulky", "suitcase", "luggage")) else 18
            cid = _cheapest_where("cargo_bin", lambda i: i["specs"]["volume_l"] >= litres)
            add(cid, 1, "Cargo bin", f"Holds ~{litres} L of packages.", ("volume_l", litres))
        elif kind == "lift":
            cid = _cheapest_where("lift", lambda i: i["specs"]["max_load_kg"] >= max(payload, 10))
            if cid is None:
                cid = "lift-actuator-150kg"
                warnings.append("Payload exceeds the strongest lift actuator.")
            add(cid, 1, "Lift", f"Raises the top plate with {max(payload, 10):g} kg on it.",
                ("max_load_kg", max(payload, 10)))
        elif kind == "vacuum":
            add(_cheapest_where("vacuum", lambda i: True), 1, "Vacuum", "Suction unit and dust bin.")
        else:
            label = {"side_brush": "Side brushes", "proximity": "Bumper sensors", "display": "Screen",
                     "speaker": "Speakers", "lights": "Lights", "pan_tilt": "Pan-tilt head"}[kind]
            reason = {"side_brush": "Sweeps dirt out of corners into the suction path.",
                      "proximity": "Detects walls and furniture before contact.",
                      "display": "Shows a face or the remote caller.", "speaker": "Talks back and plays calls.",
                      "lights": "Visibility and status for people nearby.",
                      "pan_tilt": "Points the camera without turning the whole robot."}[kind]
            add(_cheapest_where(kind, lambda i: True), 1, label, reason)

    if moving:
        est_mass = sum(c.specs.get("mass_kg", 0) * c.quantity for c in build) + arch.base_mass_kg * 0.5 + payload
        if arch.track:
            cid = _cheapest_where("track", lambda i: i["specs"]["max_load_kg"] >= est_mass)
            if cid is None:
                cid = "track-kit-alu"
                warnings.append("Robot is heavier than the strongest track kit rating.")
            add(cid, 1, "Tracks", f"Rubber tracks spread ~{est_mass:.0f} kg over rough ground.",
                ("max_load_kg", est_mass))
            radius, motors, coeff = 0.045, 2, 0.6
        else:
            per_wheel = est_mass / arch.wheels * 1.5
            indoor = has_any(text, INDOOR_WORDS) and not has_any(text, OUTDOOR_WORDS)
            cid = _cheapest_where("wheel", lambda i: i["specs"]["diameter_mm"] >= arch.wheel_mm
                                  and i["specs"]["max_load_kg"] >= per_wheel and not i["specs"].get("omni")
                                  and not (indoor and "pneumatic" in i["name"]))
            if cid is None:
                cid = "wheel-150-pneumatic"
            add(cid, arch.wheels, "Wheels", f"{arch.wheels} × {CATALOG[cid]['specs']['diameter_mm']} mm wheels for "
                                            f"~{per_wheel:.1f} kg each.", ("max_load_kg", per_wheel))
            radius, motors, coeff = CATALOG[cid]["specs"]["diameter_mm"] / 2000, arch.wheels, ROLLING_COEFF
        need = est_mass * G * radius * coeff * SAFETY / motors
        motor, ok = _cheapest("drive_motor", "torque_nm", need, arch.key)
        add(motor, motors, "Drive motors", f"~{est_mass:.1f} kg on {radius * 200:.0f} cm drive wheels needs "
                                           f"≥{need:.1f} N·m per motor ({SAFETY:g}× safety).", ("torque_nm", need))
        if not ok:
            warnings.append("Drive motors are under-sized for the estimated mass.")
        need_wh = _battery_need(build, req.runtime_hours)
        battery, ok = _cheapest("battery", "capacity_wh", need_wh)
        add(battery, 1, "Battery", f"~{_average_w(build):.0f} W average for {req.runtime_hours:g} h needs "
                                   f"≥{need_wh:.0f} Wh (80% usable).")
        if not ok:
            warnings.append(f"Runtime target needs {need_wh:.0f} Wh; the largest catalog battery is smaller.")
    else:
        decisions.append(Decision(part="Power", choice="Mains supply (not costed)",
                                  reason="Stationary robot; no battery or wheels."))
    exposed = open_deck_modules(arch)
    if exposed:
        add("printed-cover", len(exposed), "Covers", f"The {' and '.join(exposed)} sit on the open deck; "
            "printed shells keep out fingers, dust and loose parts and leave a rear notch for cables.")
    add("wiring-harness-kit", 1, "Wiring", "Harness and connectors for all modules.")

    # Budget lever: below budget -> trim; above minimum -> spend the rest on the best upgrades.
    base = [c.model_copy(deep=True) for c in build]
    upgrades: list[str] = []
    next_upgrade = None
    if req.budget_usd is not None:
        build, steps, next_upgrade = _spend_budget(build, needs, light_ids, req, moving, decisions, warnings,
                                                   arch.key)
        for before, after in zip(base, build if steps else []):
            if before.catalog_id != after.catalog_id:
                upgrades.append(f"{before.name} → {after.name}")
                decisions.append(Decision(part="Upgrade", choice=f"{before.name} → {after.name}",
                                          reason=UPGRADE_REASONS.get(after.kind, "Higher quality part.")))
        for extra in (build[len(base):] if steps else []):
            upgrades.append(f"Add {extra.name}")
            decisions.append(Decision(part="Upgrade", choice=f"Added {extra.name}",
                                      reason=UPGRADE_REASONS.get(extra.kind, "Adds capability.")))
    performance = _performance(build, moving)

    return DesignResult(components=build, robot_type=arch.label, archetype=arch.key, decisions=decisions,
                        warnings=warnings, assumptions=assumptions, requirements=req, performance=performance,
                        tier=_tier(performance), upgrades=upgrades, next_upgrade=next_upgrade,
                        concept=concept.model_dump() if concept else None)
