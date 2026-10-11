"""AI concept step: the text model designs the robot for this brief, within what the
catalog and CAD can really build. The configurator then sizes real parts for it.

The model chooses a chassis (a real catalog frame family) and composes everything
on it: modules, mast, camera mount, arm, size, payload and runtime. Anything the
chassis can't physically carry is dropped here, so the concept is always buildable.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Literal

from pydantic import BaseModel, Field

from roboforge.archetypes import ARCHETYPES, Archetype
from roboforge.models import Requirements
from roboforge.research import Research, prompt_block

Chassis = Literal["mobile_robot", "mobile_manipulator", "delivery_rover", "warehouse_amr", "cleaning_robot",
                  "telepresence", "security_patrol", "tracked_explorer", "stationary_arm"]
Module = Literal["pan_tilt", "display", "speaker", "lights", "cargo_bin", "lift", "vacuum", "side_brush",
                 "proximity"]

CHASSIS_GUIDE = {
    "mobile_robot": "open aluminium-extrusion 2-wheel base, 40x32 cm, sensor mast; general indoor carrier",
    "mobile_manipulator": "same 2-wheel extrusion base with a 5-joint arm and gripper; indoor picking and fetching",
    "delivery_rover": "sealed 4-wheel aluminium rover, 58x44 cm; sidewalks, campuses, hospitals, follow-me carts",
    "warehouse_amr": "low steel 4-wheel AMR, 74x54 cm, lifting top plate, up to 150 kg; totes, shelves, carts",
    "cleaning_robot": "round 34 cm low-profile shell with vacuum, side brushes and bumper; floor cleaning only",
    "telepresence": "round 40 cm base with a tall neck and a screen head; video calls, companions, guides",
    "security_patrol": "round 46 cm base with a sensor tower and pan-tilt camera; patrol and inspection",
    "tracked_explorer": "rugged aluminium tracked hull, 56x42 cm; outdoor, rough ground, farms, gardens",
    "stationary_arm": "bench-mounted 5-joint arm with a camera post; desk, kitchen counter, workbench jobs",
}
MODULE_GUIDE = {
    "pan_tilt": "motorised pan-tilt / gimbal camera head", "display": "touch screen", "speaker": "speakers",
    "lights": "LED light bar", "cargo_bin": "lockable cargo bin", "lift": "lifting top plate (warehouse_amr only)",
    "vacuum": "suction unit (cleaning_robot only)", "side_brush": "side brushes (cleaning_robot only)",
    "proximity": "bumper + ToF obstacle sensors",
}
# What each chassis can physically carry (and the CAD layout can place).
ALLOWED = {
    "mobile_robot": {"pan_tilt", "display", "speaker", "lights", "cargo_bin", "proximity"},
    "mobile_manipulator": {"pan_tilt", "display", "speaker", "lights", "cargo_bin", "proximity"},
    "delivery_rover": {"pan_tilt", "display", "speaker", "lights", "cargo_bin", "proximity"},
    "warehouse_amr": {"lift", "lights", "speaker", "proximity"},
    "cleaning_robot": {"vacuum", "side_brush", "proximity", "speaker"},
    "telepresence": {"display", "speaker", "lights", "pan_tilt"},
    "security_patrol": {"pan_tilt", "lights", "speaker", "display"},
    "tracked_explorer": {"pan_tilt", "lights", "speaker", "cargo_bin"},
    "stationary_arm": {"speaker", "lights", "display"},
}
ARM_CHASSIS = {"mobile_manipulator", "mobile_robot", "tracked_explorer", "stationary_arm"}


class Reason(BaseModel):
    part: str
    why: str


class Concept(BaseModel):
    name: str = Field(description="Short product-style name for this robot, e.g. 'Follow-me camera robot'")
    summary: str = Field(description="One sentence: what it is and how it does the job")
    reference: str = Field(description="The one or two real robots this design follows, max 12 words")
    photo: int | None = Field(None, description="Number of the reference photo this design is modelled on, if any")
    unsupported: str | None = Field(None, description="Set only if no ground robot can do this job; say why")
    chassis: Chassis
    arm: bool = Field(description="Needs a robot arm and gripper")
    modules: list[Module] = Field(default_factory=list)
    voice: bool = Field(description="Takes spoken commands")
    lidar: bool = Field(description="Needs 360° lidar to navigate on its own")
    mast_m: float = Field(0.35, ge=0, le=1.3, description="Height of camera mast/neck above the body, metres")
    camera_mount: Literal["front", "mast", "head", "post"] = "mast"
    size_scale: float = Field(1.0, ge=0.8, le=1.4, description="Body size vs the chassis default")
    payload_kg: float = Field(1.0, ge=0, le=150)
    runtime_h: float = Field(2.0, ge=0.5, le=10)
    outdoor: bool = False
    missing_tools: list[str] = Field(default_factory=list,
                                     description="Job tools the modules don't cover, short nouns (max 4 words), e.g. 'water pump'")
    reasons: list[Reason] = Field(default_factory=list, description="Why each major choice, one line each")


SYSTEM = (
    "You are a senior robotics engineer designing a buildable prototype for the brief. Design it the way a real "
    "company would (name comparable products), but only from these building blocks.\n"
    "Chassis (pick one):\n" + "\n".join(f"- {k}: {v}" for k, v in CHASSIS_GUIDE.items()) +
    "\nModules (add only what the job needs):\n" + "\n".join(f"- {k}: {v}" for k, v in MODULE_GUIDE.items()) +
    "\nEvery robot also gets a depth camera, a computer, power and drive. Set arm=true only for grasping jobs. "
    "Ground robots only: if the job needs flying, swimming or climbing walls, fill unsupported. If the job needs "
    "a tool that isn't listed (pump, blade, sprayer...), design the carrier and list the tool in missing_tools. "
    "mast_m: tall (0.8-1.2) for eye-level cameras or screens, 0 when nothing needs height. Keep text short.\n"
    "When real robots are listed, pick the one closest to the brief and copy its layout: base shape and size, "
    "wheels or tracks, mast or neck height, where the arm, screen and camera sit. Name it in reference and set "
    "photo to its photo number. Ignore humanoids, legs and anything these blocks can't build."
)


class ConceptError(ValueError):
    pass


def design_concept(req: Requirements, research: Research | None = None) -> Concept:
    from roboforge.llm import generate_structured
    brief = " ".join([req.description, *req.tasks]).strip()
    facts = [f"Budget: ${req.budget_usd:,.0f}" if req.budget_usd else "",
             f"Payload: {req.payload_kg:g} kg" if req.payload_kg else "",
             f"Runtime: {req.runtime_hours:g} h" if req.runtime_hours else "",
             prompt_block(research) if research else ""]
    concept = generate_structured(SYSTEM, "\n".join([f"Brief: {brief}", *filter(None, facts)]), Concept)
    if concept.photo is not None and not (research and 0 <= concept.photo < len(research.images)):
        concept = concept.model_copy(update={"photo": None})
    if concept.unsupported:
        raise ConceptError(concept.unsupported)
    return buildable(concept)


def buildable(concept: Concept) -> Concept:
    """Drop what the chassis can't carry; move arm jobs onto a chassis that has an arm."""
    chassis = concept.chassis
    if concept.arm and chassis not in ARM_CHASSIS:
        chassis = "tracked_explorer" if concept.outdoor else "mobile_manipulator"
    if chassis == "mobile_robot" and concept.arm:
        chassis = "mobile_manipulator"
    modules = [m for m in dict.fromkeys(concept.modules) if m in ALLOWED[chassis]]
    mast = concept.mast_m if chassis in ("mobile_robot", "mobile_manipulator", "telepresence",
                                         "security_patrol") else 0.0
    dropped = set(concept.modules) - set(modules)
    reasons = [r for r in concept.reasons if not any(m in r.part.lower() for m in dropped)]
    return concept.model_copy(update={"chassis": chassis, "modules": modules, "mast_m": mast, "reasons": reasons,
                                      "arm": concept.arm and chassis in ARM_CHASSIS})


def to_archetype(concept: Concept) -> Archetype:
    base = ARCHETYPES[concept.chassis]
    length, width = base.size_m
    s = concept.size_scale
    moving = base.wheels > 0 or base.track
    return replace(base, label=concept.name, blurb=concept.summary, size_m=(round(length * s, 3), round(width * s, 3)),
                   arm=concept.arm, nav_lidar=concept.lidar and moving, modules=tuple(concept.modules),
                   mast_m=concept.mast_m or base.mast_m, runtime_h=concept.runtime_h if moving else base.runtime_h,
                   wheel_mm=150 if concept.outdoor and base.wheels else base.wheel_mm,
                   camera=concept.camera_mount if concept.chassis in ("mobile_robot", "mobile_manipulator")
                   else base.camera)
