"""Reviewed geometry factories. All dimensions in mm; XY plane, Z up."""
from __future__ import annotations

from cadgen import build123d as bd

from roboforge.cad.spec import VENT_PITCH_MM, VENT_WIDTH_MM, PartSpec


def hole_positions(spec: PartSpec) -> list[tuple[float, float]]:
    if spec.kind == "cover":
        f = cover_features(spec)["flange_mm"]
        x, y = spec.length_mm / 2 + f / 2, spec.width_mm / 2 + f / 2
        return [(a, b) for a in (-x, x) for b in (-y, y)]
    x = spec.length_mm / 2 - spec.hole_inset_mm
    if spec.kind == "arm_link":
        return [(-x, 0), (x, 0)]
    y = spec.width_mm / 2 - spec.hole_inset_mm
    return [(a, b) for a in (-x, x) for b in (-y, y)]


def cover_features(spec: PartSpec) -> dict:
    """Cover layout: shell L x W x H (open bottom), flange ring outside it, top vents, rear cable notch."""
    t, k = spec.thickness_mm, spec.vent_slots
    return {"flange_mm": 2 * spec.hole_inset_mm,
            "notch_mm": (min(30.0, spec.width_mm / 3), min(12.0, (spec.height_mm - t) / 2)),  # width, height
            "vent_mm": (VENT_WIDTH_MM, (spec.width_mm - 2 * t) * 0.6),                        # along X, along Y
            "vent_x": [(i - (k - 1) / 2) * VENT_PITCH_MM for i in range(k)]}


def _cover(spec: PartSpec):
    L, W, H, t = spec.length_mm, spec.width_mm, spec.height_mm, spec.thickness_mm
    feat = cover_features(spec)
    f, (nw, nh), (vw, vl) = feat["flange_mm"], feat["notch_mm"], feat["vent_mm"]
    low = (bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN)
    body = bd.Box(L, W, H, align=low) - bd.Pos(0, 0, -1) * bd.Box(L - 2 * t, W - 2 * t, H - t + 1, align=low)
    body = body + (bd.Box(L + 2 * f, W + 2 * f, t, align=low)
                   - bd.Pos(0, 0, -1) * bd.Box(L - 2 * t, W - 2 * t, t + 2, align=low))
    for x, y in hole_positions(spec):
        body = body - bd.Pos(x, y, -1) * bd.Cylinder(spec.hole_diameter_mm / 2, t + 2, align=low)
    for x in feat["vent_x"]:
        body = body - bd.Pos(x, 0, H - t - 1) * bd.Box(vw, vl, t + 2, align=low)
    start, end = -(L / 2 + f) - 1, -L / 2 + t  # cut through the rear flange and wall
    body = body - bd.Pos((start + end) / 2, 0, -1) * bd.Box(end - start, nw, nh + 1, align=low)
    return body


def build_part(spec: PartSpec):
    if spec.kind == "cover":
        body = _cover(spec)
        body.label = spec.kind
        return body
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
