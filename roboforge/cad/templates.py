"""Reviewed geometry factories. All dimensions in mm; XY plane, Z up."""
from __future__ import annotations

from cadgen import build123d as bd

from roboforge.cad.spec import PartSpec


def hole_positions(spec: PartSpec) -> list[tuple[float, float]]:
    x = spec.length_mm / 2 - spec.hole_inset_mm
    if spec.kind == "arm_link":
        return [(-x, 0), (x, 0)]
    y = spec.width_mm / 2 - spec.hole_inset_mm
    return [(a, b) for a in (-x, x) for b in (-y, y)]


def build_part(spec: PartSpec):
    body = bd.Box(spec.length_mm, spec.width_mm, spec.thickness_mm,
                  align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN))
    if spec.kind == "motor_bracket":
        upright = bd.Pos(-spec.length_mm / 2, 0, 0) * bd.Box(
            spec.thickness_mm, spec.width_mm, spec.bracket_height_mm,
            align=(bd.Align.MIN, bd.Align.CENTER, bd.Align.MIN),
        )
        body = body + upright
    for x, y in hole_positions(spec):
        bore = bd.Pos(x, y, -1) * bd.Cylinder(
            spec.hole_diameter_mm / 2, spec.thickness_mm + 2,
            align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN),
        )
        body = body - bore
    body.label = spec.kind
    return body
