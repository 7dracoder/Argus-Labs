"""Reviewed geometry factories. All dimensions in mm; XY plane, Z up.

Parts are constructive CSG (boxes/cylinders only) so builds stay fast and
volume/envelope checks stay exact. Each kind is visually distinct so different
robots do not collapse to the same blank rectangle.
"""
from __future__ import annotations

import math

from cadgen import build123d as bd

from roboforge.cad.spec import PartSpec

ALIGN_MIN = (bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN)


def bolt_hole_diameter(spec: PartSpec) -> float:
    return max(2.5, min(spec.hole_diameter_mm * 0.55, 8.0))


def hole_positions(spec: PartSpec) -> list[tuple[float, float]]:
    if spec.kind == "wheel_hub":
        radius = spec.width_mm / 2
        return [(radius * math.cos(angle), radius * math.sin(angle))
                for angle in (math.pi / 4, 3 * math.pi / 4, 5 * math.pi / 4, 7 * math.pi / 4)]
    if spec.kind == "arm_link":
        x = spec.length_mm / 2 - spec.hole_inset_mm
        return [(-x, 0), (x, 0)]
    if spec.kind == "gripper_jaw":
        # Two bores along the finger center-line near the mount end (real parallel-jaw pattern).
        x0 = -spec.length_mm / 2 + spec.hole_inset_mm
        span = max(spec.hole_diameter_mm + 6, 12)
        return [(x0, 0), (x0 + span, 0)]
    if spec.kind == "sensor_mount":
        x = spec.length_mm / 2 - spec.hole_inset_mm
        y = spec.width_mm / 2 - spec.hole_inset_mm
        return [(x, -y), (x, y)]
    x = spec.length_mm / 2 - spec.hole_inset_mm
    y = spec.width_mm / 2 - spec.hole_inset_mm
    return [(a, b) for a in (-x, x) for b in (-y, y)]


def mounting_hole_diameter(spec: PartSpec) -> float:
    return bolt_hole_diameter(spec) if spec.kind == "wheel_hub" else spec.hole_diameter_mm


def expected_envelope(spec: PartSpec) -> list[float]:
    if spec.kind == "wheel_hub":
        collar = max(3.0, spec.thickness_mm * 0.45)
        return [spec.length_mm, spec.length_mm, spec.thickness_mm + collar]
    if spec.kind == "motor_bracket":
        return [spec.length_mm, spec.width_mm, spec.bracket_height_mm]
    if spec.kind == "sensor_mount":
        return [spec.length_mm, spec.width_mm, spec.bracket_height_mm]
    if spec.kind == "gripper_jaw":
        return [spec.length_mm, spec.width_mm, spec.thickness_mm + 1.5]
    return [spec.length_mm, spec.width_mm, spec.thickness_mm]


def _cable_cutout(spec: PartSpec) -> tuple[float, float]:
    return (min(spec.length_mm * 0.34, spec.length_mm - 36),
            min(spec.width_mm * 0.28, spec.width_mm - 28))


def _pocket(spec: PartSpec) -> tuple[float, float]:
    return (min(spec.length_mm * 0.42, spec.length_mm - 2 * spec.hole_inset_mm - 16),
            min(spec.width_mm * 0.42, spec.width_mm - 8))


def _rib(spec: PartSpec) -> tuple[float, float, float]:
    length = max(8.0, spec.length_mm - spec.thickness_mm - 10)
    thick = max(2.5, min(4.0, spec.thickness_mm))
    height = spec.bracket_height_mm - spec.thickness_mm
    return length, thick, height


def expected_volume(spec: PartSpec) -> float:
    radius = mounting_hole_diameter(spec) / 2
    holes = hole_positions(spec)
    if spec.kind == "chassis_plate":
        cut_l, cut_w = _cable_cutout(spec)
        volume = spec.length_mm * spec.width_mm * spec.thickness_mm
        volume -= cut_l * cut_w * spec.thickness_mm
        volume -= len(holes) * math.pi * radius ** 2 * spec.thickness_mm
        return volume
    if spec.kind == "arm_link":
        # Capsule: central box + two end cylinders with half-overlap each.
        volume = (spec.length_mm - spec.width_mm) * spec.width_mm * spec.thickness_mm
        volume += math.pi * (spec.width_mm / 2) ** 2 * spec.thickness_mm
        pocket_l, pocket_w = _pocket(spec)
        volume -= pocket_l * pocket_w * spec.thickness_mm
        volume -= len(holes) * math.pi * radius ** 2 * spec.thickness_mm
        return volume
    if spec.kind == "motor_bracket":
        volume = spec.length_mm * spec.width_mm * spec.thickness_mm
        volume += spec.thickness_mm * spec.width_mm * (spec.bracket_height_mm - spec.thickness_mm)
        rib_l, rib_t, rib_h = _rib(spec)
        volume += rib_l * rib_t * rib_h
        volume -= len(holes) * math.pi * radius ** 2 * spec.thickness_mm
        return volume
    if spec.kind == "wheel_hub":
        od_r = spec.length_mm / 2
        axle_r = spec.hole_diameter_mm / 2
        collar_h = max(3.0, spec.thickness_mm * 0.45)
        collar_r = min(od_r * 0.42, spec.width_mm / 2 - bolt_hole_diameter(spec))
        volume = math.pi * od_r ** 2 * spec.thickness_mm
        volume += math.pi * collar_r ** 2 * collar_h
        volume -= math.pi * axle_r ** 2 * (spec.thickness_mm + collar_h)
        volume -= len(holes) * math.pi * radius ** 2 * spec.thickness_mm
        return volume
    if spec.kind == "gripper_jaw":
        volume = spec.length_mm * spec.width_mm * spec.thickness_mm
        # Three raised grip ridges on the top face.
        ridge_l, ridge_w, ridge_h = 5.0, spec.width_mm * 0.72, 1.5
        volume += 3 * ridge_l * ridge_w * ridge_h
        # Tip relief notches (two side boxes).
        tip_l, tip_w = 14.0, spec.width_mm * 0.22
        volume -= 2 * tip_l * tip_w * spec.thickness_mm
        volume -= len(holes) * math.pi * radius ** 2 * spec.thickness_mm
        return volume
    # sensor_mount
    volume = spec.length_mm * spec.width_mm * spec.thickness_mm
    volume += spec.thickness_mm * spec.width_mm * (spec.bracket_height_mm - spec.thickness_mm)
    slot_w, slot_h = spec.width_mm * 0.42, min(18.0, spec.bracket_height_mm * 0.35)
    volume -= spec.thickness_mm * slot_w * slot_h
    volume -= len(holes) * math.pi * radius ** 2 * spec.thickness_mm
    return volume


def _bore(x: float, y: float, diameter: float, height: float, z: float = -1):
    return bd.Pos(x, y, z) * bd.Cylinder(
        diameter / 2, height, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN),
    )


def _build_chassis(spec: PartSpec):
    body = bd.Box(spec.length_mm, spec.width_mm, spec.thickness_mm, align=ALIGN_MIN)
    cut_l, cut_w = _cable_cutout(spec)
    body -= bd.Box(cut_l, cut_w, spec.thickness_mm + 2, align=ALIGN_MIN)
    for x, y in hole_positions(spec):
        body -= _bore(x, y, spec.hole_diameter_mm, spec.thickness_mm + 2)
    return body


def _build_arm_link(spec: PartSpec):
    radius = spec.width_mm / 2
    box_len = spec.length_mm - spec.width_mm
    body = bd.Box(box_len, spec.width_mm, spec.thickness_mm, align=ALIGN_MIN)
    for x in (-box_len / 2, box_len / 2):
        body += bd.Pos(x, 0, 0) * bd.Cylinder(radius, spec.thickness_mm, align=ALIGN_MIN)
    pocket_l, pocket_w = _pocket(spec)
    body -= bd.Box(pocket_l, pocket_w, spec.thickness_mm + 2, align=ALIGN_MIN)
    for x, y in hole_positions(spec):
        body -= _bore(x, y, spec.hole_diameter_mm, spec.thickness_mm + 2)
    return body


def _build_motor_bracket(spec: PartSpec):
    body = bd.Box(spec.length_mm, spec.width_mm, spec.thickness_mm, align=ALIGN_MIN)
    upright = bd.Pos(-spec.length_mm / 2, 0, 0) * bd.Box(
        spec.thickness_mm, spec.width_mm, spec.bracket_height_mm,
        align=(bd.Align.MIN, bd.Align.CENTER, bd.Align.MIN),
    )
    body += upright
    rib_l, rib_t, rib_h = _rib(spec)
    rib = bd.Pos(-spec.length_mm / 2 + spec.thickness_mm, 0, spec.thickness_mm) * bd.Box(
        rib_l, rib_t, rib_h, align=(bd.Align.MIN, bd.Align.CENTER, bd.Align.MIN),
    )
    body += rib
    for x, y in hole_positions(spec):
        body -= _bore(x, y, spec.hole_diameter_mm, spec.thickness_mm + 2)
    return body


def _build_wheel_hub(spec: PartSpec):
    od_r = spec.length_mm / 2
    collar_h = max(3.0, spec.thickness_mm * 0.45)
    collar_r = min(od_r * 0.42, spec.width_mm / 2 - bolt_hole_diameter(spec))
    body = bd.Cylinder(od_r, spec.thickness_mm, align=ALIGN_MIN)
    body += bd.Pos(0, 0, spec.thickness_mm) * bd.Cylinder(collar_r, collar_h, align=ALIGN_MIN)
    body -= _bore(0, 0, spec.hole_diameter_mm, spec.thickness_mm + collar_h + 2)
    bolt = bolt_hole_diameter(spec)
    for x, y in hole_positions(spec):
        body -= _bore(x, y, bolt, spec.thickness_mm + 2)
    return body


def _build_gripper_jaw(spec: PartSpec):
    body = bd.Box(spec.length_mm, spec.width_mm, spec.thickness_mm, align=ALIGN_MIN)
    tip_l, tip_w = 14.0, spec.width_mm * 0.22
    tip_x = spec.length_mm / 2 - tip_l / 2
    for sign in (-1, 1):
        body -= bd.Pos(tip_x, sign * (spec.width_mm / 2 - tip_w / 2), -1) * bd.Box(
            tip_l, tip_w, spec.thickness_mm + 2, align=ALIGN_MIN,
        )
    ridge_l, ridge_w, ridge_h = 5.0, spec.width_mm * 0.72, 1.5
    tip = spec.length_mm / 2 - 12
    for index in range(3):
        body += bd.Pos(tip - index * 8, 0, spec.thickness_mm) * bd.Box(
            ridge_l, ridge_w, ridge_h, align=ALIGN_MIN,
        )
    for x, y in hole_positions(spec):
        body -= _bore(x, y, spec.hole_diameter_mm, spec.thickness_mm + 2)
    return body


def _build_sensor_mount(spec: PartSpec):
    body = bd.Box(spec.length_mm, spec.width_mm, spec.thickness_mm, align=ALIGN_MIN)
    upright = bd.Pos(-spec.length_mm / 2, 0, 0) * bd.Box(
        spec.thickness_mm, spec.width_mm, spec.bracket_height_mm,
        align=(bd.Align.MIN, bd.Align.CENTER, bd.Align.MIN),
    )
    body += upright
    slot_w, slot_h = spec.width_mm * 0.42, min(18.0, spec.bracket_height_mm * 0.35)
    slot_z = spec.thickness_mm + (spec.bracket_height_mm - spec.thickness_mm) / 2
    body -= bd.Pos(-spec.length_mm / 2 - 1, 0, slot_z) * bd.Box(
        spec.thickness_mm + 2, slot_w, slot_h,
        align=(bd.Align.MIN, bd.Align.CENTER, bd.Align.CENTER),
    )
    for x, y in hole_positions(spec):
        body -= _bore(x, y, spec.hole_diameter_mm, spec.thickness_mm + 2)
    return body


_BUILDERS = {
    "chassis_plate": _build_chassis,
    "arm_link": _build_arm_link,
    "motor_bracket": _build_motor_bracket,
    "wheel_hub": _build_wheel_hub,
    "gripper_jaw": _build_gripper_jaw,
    "sensor_mount": _build_sensor_mount,
}


def build_part(spec: PartSpec):
    body = _BUILDERS[spec.kind](spec)
    body.label = spec.kind
    return body
