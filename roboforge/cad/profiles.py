"""Map robot requirements to a distinctive signature part.

Different robots should not collapse to the same arm-link default. This module
picks one reviewed template and sized defaults from mobility, tasks, and payload.
"""
from __future__ import annotations

from roboforge.cad.spec import PART_KINDS, PartKind, PartSpec
from roboforge.models import Requirements

KIND_GUIDE: dict[PartKind, str] = {
    "chassis_plate": "Rectangular base plate with four corner mounts and a center cable pass-through; for wheeled or fixed platforms.",
    "arm_link": "Capsule-ended servo/arm link with two pivot bores and a lightening pocket; for manipulators and legged limbs.",
    "motor_bracket": "L-shaped actuator bracket with base mounts and a stiffening rib; upright has no motor bolt pattern yet.",
    "wheel_hub": "Circular drive flange: outer diameter×thickness disc, center axle bore, four bolt-circle holes; for wheeled mobility.",
    "gripper_jaw": "Parallel-gripper finger with base mounts and grip serrations; for pick-and-place end effectors.",
    "sensor_mount": "Camera/depth mount with base holes and an upright window slot; for perception payloads.",
}


def _blob(requirements: Requirements) -> str:
    return " ".join([
        requirements.description or "",
        " ".join(requirements.tasks or []),
        requirements.mobility or "",
        requirements.environment or "",
        " ".join(requirements.assumptions or []),
    ]).lower()


def _scale(payload_kg: float | None) -> float:
    payload = 1.0 if payload_kg is None else max(0.2, float(payload_kg))
    return max(0.75, min(1.75, 0.9 + payload / 6.0))


def suggest_signature_part(requirements: Requirements) -> PartSpec:
    """Return one distinctive part sized for this robot brief."""
    text = _blob(requirements)
    mobility = (requirements.mobility or "").lower()
    scale = _scale(requirements.payload_kg)

    def sized(**kwargs) -> PartSpec:
        return PartSpec(**kwargs)

    if any(token in text for token in ("gripper", "grasp", "claw", "finger", "pick up", "pick-and-place", "end effector")):
        return sized(
            name="Gripper jaw",
            kind="gripper_jaw",
            length_mm=round(70 * scale, 1),
            width_mm=round(22 * min(scale, 1.3), 1),
            thickness_mm=6,
            hole_diameter_mm=3.2,
            hole_inset_mm=10,
            material="petg",
        )
    if any(token in text for token in ("camera", "vision", "depth", "realsense", "oak", "lidar", "sensor mount")):
        return sized(
            name="Sensor mount",
            kind="sensor_mount",
            length_mm=round(70 * scale, 1),
            width_mm=round(50 * min(scale, 1.4), 1),
            thickness_mm=4,
            hole_diameter_mm=3.2,
            hole_inset_mm=12,
            bracket_height_mm=round(48 * min(scale, 1.4), 1),
            material="petg",
        )
    if mobility == "wheeled" or "wheel" in text or "rover" in text or "mobile base" in text:
        if any(token in text for token in ("arm", "manipulat", "servo", "humanoid")):
            return sized(
                name="Mobile base chassis plate",
                kind="chassis_plate",
                length_mm=round(220 * scale, 1),
                width_mm=round(160 * scale, 1),
                thickness_mm=5,
                hole_diameter_mm=4,
                hole_inset_mm=12,
                material="petg",
            )
        return sized(
            name="Drive wheel hub",
            kind="wheel_hub",
            length_mm=round(80 * scale, 1),
            width_mm=round(48 * scale, 1),
            thickness_mm=8,
            hole_diameter_mm=round(12 * min(scale, 1.3), 1),
            hole_inset_mm=10,
            material="aluminum",
        )
    if mobility == "legged" or any(token in text for token in ("arm link", "manipulator", "servo arm", "humanoid", "limb")):
        return sized(
            name="Arm link",
            kind="arm_link",
            length_mm=round(140 * scale, 1),
            width_mm=round(28 * min(scale, 1.4), 1),
            thickness_mm=6,
            hole_diameter_mm=4,
            hole_inset_mm=12,
            material="petg",
        )
    if any(token in text for token in ("motor bracket", "gear motor", "actuator mount", "nema")):
        return sized(
            name="Motor bracket",
            kind="motor_bracket",
            length_mm=round(60 * scale, 1),
            width_mm=round(50 * min(scale, 1.4), 1),
            thickness_mm=4,
            hole_diameter_mm=3.2,
            hole_inset_mm=14,
            bracket_height_mm=round(45 * min(scale, 1.4), 1),
            material="petg",
        )
    if mobility == "fixed" or "gantry" in text or "stationary" in text:
        return sized(
            name="Platform chassis plate",
            kind="chassis_plate",
            length_mm=round(180 * scale, 1),
            width_mm=round(120 * scale, 1),
            thickness_mm=5,
            hole_diameter_mm=4,
            hole_inset_mm=12,
            material="petg",
        )
    return sized(
        name="Utility chassis plate",
        kind="chassis_plate",
        length_mm=round(160 * scale, 1),
        width_mm=round(110 * scale, 1),
        thickness_mm=5,
        hole_diameter_mm=4,
        hole_inset_mm=12,
        material="petg",
    )


def template_catalog() -> list[dict]:
    return [{"kind": kind, "description": KIND_GUIDE[kind]} for kind in PART_KINDS]


def prompt_catalog_text() -> str:
    return "\n".join(f"- {kind}: {KIND_GUIDE[kind]}" for kind in PART_KINDS)
