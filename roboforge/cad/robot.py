"""Whole-robot CAD model built with the text-to-cad runtime (cadgen / build123d).

Each assembly node (roboforge/assembly.py) becomes a detailed B-rep part:
filleted chassis with extrusion rails, rubber tyres on machined hubs, gearmotors,
servos with horns, aluminium arm brackets, a depth camera, a computer board and
so on. Generated CAD parts are rebuilt from their reviewed templates, so the
robot contains the exact same geometry as the downloadable part.

Parts are authored in a Y-up frame (matching the viewer layout) in millimetres,
then the whole robot is rotated to Z-up for STEP. Catalog parts are
representative models sized to typical dimensions, not vendor CAD.
"""
from __future__ import annotations

import math
from typing import Callable

from cadgen import build123d as bd

from roboforge.cad.spec import PartSpec
from roboforge.cad.templates import build_part

Piece = tuple[object, str, str]  # (shape, finish, sRGB hex)

ALU, DARK_ALU, STEEL, RUBBER = "#c4c8cd", "#5a6068", "#9ea4ab", "#1b1c1e"
BLACK, CHARCOAL, GLASS = "#202326", "#2d3135", "#0a0c0f"


def _safe_fillet(shape, edges, radius):
    try:
        return bd.fillet(edges, radius) if radius > 0.05 else shape
    except Exception:  # fillet can fail on small/odd edges; keep the sharp solid
        return shape


def _safe_chamfer(shape, edges, length):
    try:
        return bd.chamfer(edges, length) if length > 0.05 else shape
    except Exception:
        return shape


def _rounded_box(x, y, z, r, axis=bd.Axis.Y):
    box = bd.Box(x, y, z)
    return _safe_fillet(box, box.edges().filter_by(axis), min(r, x / 2 - 0.1, z / 2 - 0.1, y / 2 - 0.1) if axis == bd.Axis.Y else r)


def _cyl_y(radius, height):
    """Cylinder along +Y, centred on the origin."""
    return bd.Rot(-90, 0, 0) * bd.Cylinder(radius, height)


def _cyl_x(radius, height):
    return bd.Rot(0, 90, 0) * bd.Cylinder(radius, height)


# ---------------------------------------------------------------- part models
def frame(L, H, W) -> list[Piece]:
    body = bd.Box(L, H, W)
    body = _safe_fillet(body, body.edges().filter_by(bd.Axis.Y), min(16, W * 0.07))
    for side in (1, -1):  # side vents
        for i in range(4):
            vent = bd.Pos(-L * 0.18 + i * 14, 0, side * W / 2) * bd.Box(7, H * 0.38, 6)
            body = body - vent
    pieces: list[Piece] = [(body, "paint", "#3b4147")]
    for side in (1, -1):  # aluminium extrusion rails with a T-slot groove
        rail = bd.Pos(0, H / 2 - 8, side * (W / 2 - 4.5)) * bd.Box(L - 24, 12, 12)
        rail = rail - bd.Pos(0, H / 2 - 8, side * (W / 2 + 1.5)) * bd.Box(L, 3.5, 3)
        pieces.append((rail, "metal", ALU))
    for end in (1, -1):  # rubber bumpers
        bumper = _rounded_box(6, H * 0.45, W * 0.8, 2.5, bd.Axis.X)
        pieces.append((bd.Pos(end * (L / 2 + 2.5), -H * 0.12, 0) * bumper, "rubber", RUBBER))
    return pieces


def deck(L, T, W) -> list[Piece]:
    plate = bd.Box(L, T, W)
    plate = _safe_fillet(plate, plate.edges().filter_by(bd.Axis.Y), 10)
    for x in (-L / 2 + 12, L / 2 - 12):
        for z in (-W / 2 + 12, W / 2 - 12):
            plate = plate - bd.Pos(x, 0, z) * _cyl_y(2.2, T + 2)
    return [(plate, "plastic", "#2a2d31")]


def wheel(r, w) -> list[Piece]:
    tyre = _cyl_y(r, w)
    tyre = _safe_fillet(tyre, tyre.edges(), w * 0.32)
    tyre = tyre - _cyl_y(r * 0.6, w + 2)
    for i in range(24):  # tread grooves
        a = math.radians(i * 15)
        groove = bd.Pos(r * math.cos(a), 0, r * math.sin(a)) * bd.Rot(0, -math.degrees(a), 0) * bd.Box(2.4, w * 0.7, 3)
        tyre = tyre - groove
    hub = _cyl_y(r * 0.6, w - 2)
    for i in range(5):
        a = math.radians(i * 72)
        hub = hub - bd.Pos(r * 0.36 * math.cos(a), 0, r * 0.36 * math.sin(a)) * _cyl_y(r * 0.11, w + 2)
    cap = _cyl_y(r * 0.16, w + 3)
    return [(tyre, "rubber", RUBBER), (hub, "metal", "#b9bec4"), (cap, "metal", DARK_ALU)]


def motor(r, h) -> list[Piece]:
    can = bd.Pos(0, -h * 0.2, 0) * _cyl_y(r, h * 0.55)
    can = _safe_fillet(can, can.edges(), 1.2)
    gearbox = bd.Pos(0, h * 0.27, 0) * _cyl_y(r * 1.06, h * 0.38)
    cap = bd.Pos(0, -h * 0.5 + 2, 0) * _cyl_y(r * 0.7, 4)
    shaft = bd.Pos(0, h * 0.5 + 4, 0) * _cyl_y(3, 10)
    return [(can, "metal", STEEL), (gearbox, "metal", "#8c8f94"), (cap, "plastic", BLACK), (shaft, "metal", STEEL)]


def caster(r) -> list[Piece]:
    ball = bd.Sphere(r)
    housing = bd.Pos(0, r * 0.6, 0) * _cyl_y(r * 1.35, r * 0.9)
    housing = _safe_fillet(housing, housing.edges(), 1.5)
    return [(ball, "chrome", "#d5d9dd"), (housing, "plastic", CHARCOAL)]


def battery(L, H, W) -> list[Piece]:
    pack = _rounded_box(L, H, W, 6)
    pack = _safe_fillet(pack, pack.edges().filter_by(bd.Axis.X), 3)
    label = bd.Pos(0, 0, W / 2 + 0.3) * bd.Box(L * 0.62, H * 0.5, 0.8)
    plus = bd.Pos(L * 0.3, H / 2 + 4, 0) * _cyl_y(4.5, 8)
    minus = bd.Pos(L * 0.18, H / 2 + 4, 0) * _cyl_y(4.5, 8)
    return [(pack, "plastic", "#25344a"), (label, "plastic", "#d9dee4"),
            (plus, "plastic", "#b33a2c"), (minus, "plastic", BLACK)]


def compute(L, H, W) -> list[Piece]:
    t = 1.6
    y0 = -H / 2 + t / 2
    board = bd.Box(L, t, W)
    board = _safe_fillet(board, board.edges().filter_by(bd.Axis.Y), 3)
    for x in (-L / 2 + 3.5, L / 2 - 3.5):
        for z in (-W / 2 + 3.5, W / 2 - 3.5):
            board = board - bd.Pos(x, 0, z) * _cyl_y(1.4, 4)
    pieces: list[Piece] = [(bd.Pos(0, y0, 0) * board, "pcb", "#1d5b37")]
    sink = bd.Box(24, 9, 24)
    for i in range(6):
        sink = sink - bd.Pos(-10 + i * 4, 2.5, 0) * bd.Box(1.6, 6, 26)
    pieces.append((bd.Pos(-6, y0 + t / 2 + 4.5, -2) * sink, "metal", DARK_ALU))
    for i, z in enumerate((-W / 2 + 12, -W / 2 + 30)):
        pieces.append((bd.Pos(L / 2 - 8, y0 + t / 2 + 8, z) * bd.Box(17, 16, 14), "metal", STEEL))
    pieces.append((bd.Pos(L / 2 - 10, y0 + t / 2 + 6.5, W / 2 - 14) * bd.Box(21, 13, 16), "metal", STEEL))
    pieces.append((bd.Pos(-4, y0 + t / 2 + 4, W / 2 - 4) * bd.Box(50, 8, 5), "plastic", BLACK))
    return pieces


def mast(r, h) -> list[Piece]:
    tube = _cyl_y(r, h)
    flange = bd.Pos(0, -h / 2 + 2.5, 0) * _cyl_y(r * 2.8, 5)
    flange = _safe_fillet(flange, flange.edges(), 1.2)
    clamp = bd.Pos(0, h / 2 - 6, 0) * _cyl_y(r * 1.5, 12)
    return [(tube, "metal", ALU), (flange, "metal", DARK_ALU), (clamp, "plastic", CHARCOAL)]


def camera(D, H, W) -> list[Piece]:
    housing = bd.Box(D, H, W)
    housing = _safe_fillet(housing, housing.edges(), min(5, H / 2 - 0.5))
    pieces: list[Piece] = [(housing, "paint", "#2b2f34"),
                           (bd.Pos(D / 2 + 0.4, 0, 0) * bd.Box(0.8, H * 0.75, W * 0.9), "plastic", "#14171a")]
    for z, rr in ((0, H * 0.24), (-W * 0.36, H * 0.17), (W * 0.36, H * 0.17)):
        ring = bd.Pos(D / 2 + 1.5, 0, z) * _cyl_x(rr + 1.6, 3)
        lens = bd.Pos(D / 2 + 2.3, 0, z) * _cyl_x(rr, 2)
        pieces += [(ring, "metal", DARK_ALU), (lens, "glass", GLASS)]
    return pieces


def mic(r, h) -> list[Piece]:
    disc = _cyl_y(r, h)
    disc = _safe_fillet(disc, disc.edges(), 1)
    for i in range(6):
        a = math.radians(i * 60)
        disc = disc - bd.Pos(r * 0.75 * math.cos(a), h / 2, r * 0.75 * math.sin(a)) * _cyl_y(1.5, 3)
    return [(disc, "pcb", "#16181b"), (bd.Pos(0, h / 2 + 0.5, 0) * _cyl_y(r * 0.35, 1.5), "plastic", "#7f8a96")]


def turntable(r, h) -> list[Piece]:
    base = _cyl_y(r, h * 0.7)
    base = _safe_fillet(base, base.edges(), 2)
    ring = bd.Pos(0, h * 0.4, 0) * _cyl_y(r * 0.85, h * 0.25)
    return [(bd.Pos(0, -h * 0.15, 0) * base, "paint", CHARCOAL), (ring, "metal", ALU)]


def servo(x, y, z) -> list[Piece]:
    t = z * 0.56  # body thickness along the joint axis (z)
    body = bd.Box(x, y, t)
    body = _safe_fillet(body, body.edges(), 2)
    ears = bd.Pos(0, y * 0.22, 0) * bd.Box(x + 14, 2.6, t)
    for ex in (-(x / 2 + 4), x / 2 + 4):
        ears = ears - bd.Pos(ex, y * 0.22, 0) * _cyl_y(1.6, 4)
    horn = bd.Pos(0, y * 0.22, t / 2 + 1.6) * bd.Cylinder(10, 3.2)
    horn = _safe_fillet(horn, horn.edges(), 0.8)
    screw = bd.Pos(0, y * 0.22, t / 2 + 3.6) * bd.Cylinder(2.2, 1.2)
    idler = bd.Pos(0, y * 0.22, -t / 2 - 1) * bd.Cylinder(6, 2)
    return [(body, "plastic", "#1c1f22"), (ears, "plastic", "#1c1f22"), (horn, "metal", "#d9dcdf"),
            (screw, "metal", STEEL), (idler, "metal", "#c9cdd1")]


def link(L, Y, Z) -> list[Piece]:
    pieces: list[Piece] = []
    for side in (1, -1):
        plate = bd.Box(L + Y, Y, 3)
        plate = _safe_fillet(plate, plate.edges().filter_by(bd.Axis.Z), Y / 2 - 0.2)
        slot = bd.Box(L * 0.55, Y * 0.36, 5)
        slot = _safe_fillet(slot, slot.edges().filter_by(bd.Axis.Z), Y * 0.18 - 0.2)
        plate = plate - slot
        for end in (-L / 2, L / 2):
            plate = plate - bd.Pos(end, 0, 0) * bd.Cylinder(3.2, 5)
        pieces.append((bd.Pos(0, 0, side * (Z / 2 + 1.5)) * plate, "metal", "#b7bcc2"))
    brace = bd.Box(8, Y * 0.7, Z)
    pieces.append((brace, "metal", DARK_ALU))
    return pieces


def wrist(r, h) -> list[Piece]:
    body = _cyl_y(r, h)
    body = _safe_fillet(body, body.edges(), 1.5)
    return [(body, "plastic", "#1c1f22"), (bd.Pos(0, h / 2 + 1, 0) * _cyl_y(r * 0.6, 2), "metal", "#d9dcdf")]


def gripper(x, y, z) -> list[Piece]:
    palm = bd.Box(x, y, z)
    palm = _safe_fillet(palm, palm.edges().filter_by(bd.Axis.Y), 3)
    rail = bd.Pos(0, -y / 2 - 2, 0) * bd.Box(x * 0.5, 4, z * 0.9)
    return [(palm, "metal", DARK_ALU), (rail, "metal", STEEL)]


def finger(x, y, z) -> list[Piece]:
    body = bd.Box(x, y, z)
    body = _safe_fillet(body, body.edges().filter_by(bd.Axis.Z), min(x, y) * 0.3)
    pad = bd.Pos(0, -y * 0.25, 0) * bd.Box(x * 0.9, y * 0.45, z + 1.2)
    return [(body, "plastic", "#d6d9d2"), (pad, "rubber", "#2a2c2e")]


def lidar(r, h) -> list[Piece]:
    base = bd.Pos(0, -h * 0.3, 0) * _cyl_y(r, h * 0.4)
    base = _safe_fillet(base, base.edges(), 1.5)
    head = bd.Pos(0, h * 0.2, 0) * _cyl_y(r * 0.82, h * 0.6)
    head = _safe_fillet(head, head.edges(), 2)
    window = bd.Pos(0, h * 0.18, 0) * _cyl_y(r * 0.84, h * 0.18)
    return [(base, "plastic", CHARCOAL), (head, "paint", "#111315"), (window, "glass", "#3a1a1a")]


def generic(x, y, z) -> list[Piece]:
    return [(_rounded_box(x, y, z, 3), "plastic", "#8f9a8c")]


# ---------------------------------------------------------------- variants and body-plan parts
def wheel_variant(r, w, variant=None) -> list[Piece]:
    if variant == "wheel-100-mecanum":
        hub = _cyl_y(r * 0.62, w)
        plates = [bd.Pos(0, side * w / 2, 0) * _cyl_y(r * 0.8, 2.5) for side in (1, -1)]
        pieces: list[Piece] = [(hub, "metal", DARK_ALU)] + [(pl, "metal", ALU) for pl in plates]
        for i in range(9):  # 45° rollers around the rim
            a = math.radians(i * 40)
            roller = bd.Pos(r * 0.8 * math.cos(a), 0, r * 0.8 * math.sin(a)) * bd.Rot(0, -math.degrees(a), 0) \
                * bd.Rot(45, 0, 0) * _cyl_y(r * 0.17, w * 0.95)
            roller = _safe_fillet(roller, roller.edges(), r * 0.08)
            pieces.append((roller, "rubber", "#2a2b2d"))
        return pieces
    if variant in ("wheel-150-pneumatic",):
        tyre = _cyl_y(r, w)
        tyre = _safe_fillet(tyre, tyre.edges(), w * 0.42)
        tyre = tyre - _cyl_y(r * 0.55, w + 2)
        for i in range(18):  # chunky knobs
            a = math.radians(i * 20)
            for off in (-w * 0.22, w * 0.22):
                knob = bd.Pos(r * math.cos(a), off, r * math.sin(a)) * bd.Rot(0, -math.degrees(a), 0) * bd.Box(5, w * 0.3, 7)
                tyre = tyre - knob
        rim = _cyl_y(r * 0.56, w * 0.8)
        for i in range(6):
            a = math.radians(i * 60)
            rim = rim - bd.Pos(r * 0.33 * math.cos(a), 0, r * 0.33 * math.sin(a)) * _cyl_y(r * 0.09, w + 2)
        return [(tyre, "rubber", "#161718"), (rim, "paint", "#c7a338"), (_cyl_y(r * 0.14, w + 4), "metal", STEEL)]
    if variant in ("wheel-65-rubber",):
        tyre = _cyl_y(r, w)
        tyre = _safe_fillet(tyre, tyre.edges(), w * 0.3) - _cyl_y(r * 0.7, w + 2)
        return [(tyre, "rubber", RUBBER), (_cyl_y(r * 0.7, w - 2), "plastic", "#e8e8e6")]
    if variant in ("wheel-150-pu-heavy",):
        tread = _cyl_y(r, w) - _cyl_y(r * 0.78, w + 2)
        tread = _safe_fillet(tread, tread.edges(), 2.5)
        core = _cyl_y(r * 0.78, w * 0.9)
        for i in range(8):
            a = math.radians(i * 45)
            core = core - bd.Pos(r * 0.5 * math.cos(a), 0, r * 0.5 * math.sin(a)) * _cyl_y(r * 0.1, w + 2)
        return [(tread, "rubber", "#c96d1f"), (core, "metal", "#7f858c"), (_cyl_y(r * 0.2, w + 4), "metal", STEEL)]
    return wheel(r, w)  # 100 mm PU / default


def track(L, H, W, variant=None) -> list[Piece]:
    r = H / 2
    belt = bd.Box(L - H, H, W) + bd.Pos(-(L - H) / 2, 0, 0) * bd.Cylinder(r, W) + bd.Pos((L - H) / 2, 0, 0) * bd.Cylinder(r, W)
    belt = belt - (bd.Box(L - H, H - 16, W + 2) + bd.Pos(-(L - H) / 2, 0, 0) * bd.Cylinder(r - 8, W + 2)
                   + bd.Pos((L - H) / 2, 0, 0) * bd.Cylinder(r - 8, W + 2))
    for i in range(int((L - H) / 18)):  # grousers along the top and bottom runs
        x = -(L - H) / 2 + 9 + i * 18
        for y in (H / 2 + 1.5, -H / 2 - 1.5):
            belt = belt + bd.Pos(x, y, 0) * bd.Box(5, 3, W)
    metal = variant == "track-kit-alu"
    pieces: list[Piece] = [(belt, "metal" if metal else "rubber", "#5d6166" if metal else "#1a1b1d")]
    for x in (-(L - H) / 2, (L - H) / 2):
        sprocket = bd.Pos(x, 0, 0) * bd.Cylinder(r - 10, W * 0.7)
        pieces.append((sprocket, "metal", DARK_ALU))
    for i in range(3):
        x = -(L - H) / 4 + i * (L - H) / 4
        pieces.append((bd.Pos(x, -H / 2 + 14, 0) * bd.Cylinder(12, W * 0.6), "metal", STEEL))
    side = bd.Pos(0, 4, W / 2 + 1) * _rounded_box(L - H * 0.6, H * 0.45, 2, 6, bd.Axis.Z)
    pieces.append((side, "paint", "#3b4147"))
    return pieces


def round_body(r, h, variant=None) -> list[Piece]:
    shell = bd.Cylinder(r, h)
    shell = bd.Rot(-90, 0, 0) * shell
    shell = _safe_fillet(shell, shell.edges(), min(10, h * 0.25))
    top = bd.Pos(0, h / 2 + 0.6, 0) * _cyl_y(r * 0.86, 1.2)
    return [(shell, "paint", "#e9eaeb" if r < 190 else "#f2f2f0"), (top, "plastic", "#2c2f33")]


def round_bumper(r, h, variant=None) -> list[Piece]:
    ring = _cyl_y(r, h) - _cyl_y(r - 6, h + 2)
    ring = ring - bd.Pos(-r, 0, 0) * bd.Box(2 * r, h + 4, 2 * r + 4)  # front half only
    return [(ring, "plastic", "#2b2e31")]


def dust_bin(x, y, z, variant=None) -> list[Piece]:
    lid = _rounded_box(x, max(y, 3), z, 6)
    return [(lid, "plastic", "#7b8794"), (bd.Pos(0, y / 2 + 1, 0) * bd.Box(x * 0.3, 2, z * 0.25), "plastic", "#2c2f33")]


def side_brush(r, h, variant=None) -> list[Piece]:
    hub = _cyl_y(8, 6)
    pieces: list[Piece] = [(hub, "plastic", "#2c2f33")]
    for i in range(3):
        a = 120 * i
        bristle = bd.Rot(0, a, 0) * bd.Pos(r / 2, 0, 0) * bd.Rot(0, 0, -6) * bd.Box(r, 1.6, 3)
        pieces.append((bristle, "plastic", "#4a6fa5"))
    return pieces


def cargo_bin(L, H, W, variant=None) -> list[Piece]:
    metal = variant == "alu-cargo-bin"
    box = _rounded_box(L, H, W, 22)
    box = _safe_fillet(box, box.edges().filter_by(bd.Axis.Z), 8)
    colour = ALU if metal else "#f1f1ee"
    lid_line = bd.Pos(0, H / 2 - 30, 0) * _rounded_box(L + 1.2, 2.5, W + 1.2, 22)
    handle = bd.Pos(L / 2 + 4, H / 2 - 45, 0) * _rounded_box(8, 10, W * 0.3, 3, bd.Axis.X)
    lock = bd.Pos(L / 2 + 1.5, H / 2 - 70, 0) * _cyl_x(7, 4)
    return [(box, "metal" if metal else "paint", colour), (lid_line, "plastic", "#2c2f33"),
            (handle, "plastic", BLACK), (lock, "metal", STEEL)]


def lights(x, y, z, variant=None) -> list[Piece]:
    bar = _rounded_box(x, y, z, 3, bd.Axis.X)
    lens = bd.Pos(x / 2 + 0.3, 0, 0) * bd.Box(0.8, y * 0.6, z * 0.9)
    return [(bar, "plastic", BLACK), (lens, "glass", "#f4f1e3")]


def flag(r, h, variant=None) -> list[Piece]:
    pole = _cyl_y(r, h)
    pennant = bd.Pos(0, h / 2 - 45, 0) * bd.Box(1.2, 80, 120)
    pennant = bd.Pos(0, 0, -60) * pennant
    return [(pole, "plastic", "#e0e0dc"), (pennant, "plastic", "#e8692c")]


def enclosure(L, H, W, variant=None) -> list[Piece]:
    box = _rounded_box(L, H, W, 6)
    box = _safe_fillet(box, box.edges().filter_by(bd.Axis.X), 4)
    gasket = bd.Pos(0, H / 2 - 12, 0) * _rounded_box(L + 1, 2, W + 1, 6)
    pieces: list[Piece] = [(box, "paint", "#4b5a3f"), (gasket, "rubber", RUBBER)]
    for i in range(4):
        pieces.append((bd.Pos(-L / 2 + 15 + i * (L - 30) / 3, H / 2 + 1, W / 2 - 10) * _cyl_y(3, 2), "metal", STEEL))
    return pieces


def tower(r, h, variant=None) -> list[Piece]:
    body = _cyl_y(r, h)
    body = _safe_fillet(body, body.edges().group_by(bd.Axis.Y)[-1], r * 0.45)
    band = bd.Pos(0, h * 0.28, 0) * _cyl_y(r + 0.6, h * 0.12)
    ring = bd.Pos(0, -h / 2 + 6, 0) * _cyl_y(r * 1.35, 12)
    ring = _safe_fillet(ring, ring.edges(), 3)
    return [(body, "paint", "#eceeef"), (band, "glass", GLASS), (ring, "rubber", CHARCOAL)]


def pan_tilt(r, h, variant=None) -> list[Piece]:
    base = bd.Pos(0, -h / 2 + 8, 0) * _cyl_y(r, 16)
    base = _safe_fillet(base, base.edges(), 3)
    yoke = bd.Pos(0, 6, 0) * (bd.Pos(0, 0, r * 0.65) * bd.Box(16, h - 16, 5) + bd.Pos(0, 0, -r * 0.65) * bd.Box(16, h - 16, 5))
    gimbal = variant == "pan-tilt-gimbal"
    return [(base, "metal" if gimbal else "plastic", DARK_ALU if gimbal else CHARCOAL), (yoke, "metal", ALU)]


def amr_body(L, H, W, variant=None) -> list[Piece]:
    body = bd.Box(L, H, W)
    body = _safe_fillet(body, body.edges().filter_by(bd.Axis.Y), 40)
    body = _safe_fillet(body, body.edges().group_by(bd.Axis.Y)[-1], 8)
    skirt = bd.Pos(0, -H / 2 + 12, 0) * _rounded_box(L + 10, 24, W + 10, 44)
    notch = bd.Pos(L / 2, -H / 2 + 30, 0) * bd.Box(70, 34, 120)
    body = body - notch
    return [(body, "paint", "#e7e9ea"), (skirt, "rubber", "#2b2e31")]


def lift_plate(L, T, W, variant=None) -> list[Piece]:
    plate = bd.Box(L, T, W)
    plate = _safe_fillet(plate, plate.edges().filter_by(bd.Axis.Y), 30)
    pad = bd.Pos(0, T / 2 + 1, 0) * _rounded_box(L * 0.9, 2, W * 0.9, 26)
    return [(plate, "paint", "#31363b"), (pad, "rubber", "#1d1f21")]


def lift_column(r, h, variant=None) -> list[Piece]:
    return [(_cyl_y(r, h), "chrome", "#d5d9dd"), (bd.Pos(0, -h / 2 + 3, 0) * _cyl_y(r * 1.5, 6), "metal", DARK_ALU)]


def estop(r, h, variant=None) -> list[Piece]:
    base = _cyl_y(r * 1.3, h * 0.5)
    cap = bd.Pos(0, h * 0.4, 0) * _cyl_y(r, h * 0.5)
    cap = _safe_fillet(cap, cap.edges(), 2)
    return [(base, "plastic", "#f0c419"), (cap, "plastic", "#c0262d")]


def display(D, H, W, variant=None) -> list[Piece]:
    bezel = _rounded_box(D, H, W, 8)
    bezel = _safe_fillet(bezel, bezel.edges().filter_by(bd.Axis.X), 6)
    screen = bd.Pos(D / 2 + 0.3, 0, 0) * bd.Box(0.8, H - 12, W - 12)
    return [(bezel, "paint", "#1f2226"), (screen, "glass", "#0d1b2a")]


def speaker(D, H, W, variant=None) -> list[Piece]:
    body = _rounded_box(D, H, W, 10)
    for i in range(7):
        body = body - bd.Pos(D / 2, -H / 3 + i * (H / 9), 0) * bd.Box(4, 2, W * 0.8)
    return [(body, "paint", "#2a2d31")]


def button(r, h, variant=None) -> list[Piece]:
    cap = _cyl_y(r, h)
    return [(_safe_fillet(cap, cap.edges(), min(h / 2 - 0.2, 2)), "plastic", "#5c7a5a")]


# ---------------------------------------------------------------- catalog-specific models
# Each catalog id gets its own recognisable shape and finish, so two robots with
# different parts never share the same model. Built from boxes/cylinders with a
# few fillets to keep whole-robot builds fast.

def frame_variant(L, H, W, variant=None) -> list[Piece]:
    if variant == "alu-extrusion-frame":
        s = min(20.0, H / 3)  # 2020 aluminium profile
        pieces: list[Piece] = []
        for y in (H / 2 - s / 2, -H / 2 + s / 2):
            for z in (W / 2 - s / 2, -W / 2 + s / 2):
                rail = bd.Pos(0, y, z) * bd.Box(L, s, s)
                rail = rail - bd.Pos(0, y, z + math.copysign(s / 2, z)) * bd.Box(L + 2, s * 0.3, s * 0.3)
                pieces.append((rail, "metal", ALU))
            for x in (L / 2 - s / 2, -L / 2 + s / 2):
                pieces.append((bd.Pos(x, y, 0) * bd.Box(s, s, W - 2 * s), "metal", ALU))
        for x in (L / 2 - s / 2, -L / 2 + s / 2):
            for z in (W / 2 - s / 2, -W / 2 + s / 2):
                pieces.append((bd.Pos(x, 0, z) * bd.Box(s, H - 2 * s, s), "metal", ALU))
                pieces.append((bd.Pos(x, H / 2 + 1, z) * bd.Box(s, 2, s), "plastic", BLACK))  # end caps
        for z in (W / 2 - s / 2, -W / 2 + s / 2):  # smoked acrylic side panels
            pieces.append((bd.Pos(0, 0, z) * bd.Box(L - 2 * s, H - 2 * s, 3), "glass", "#1e2226"))
        pieces.append((bd.Pos(0, -H / 2 + s / 2, 0) * bd.Box(L - 2 * s, 3, W - 2 * s), "metal", DARK_ALU))
        return pieces
    if variant == "printed-petg-chassis":
        body = bd.Box(L, H, W)
        body = _safe_fillet(body, body.edges().filter_by(bd.Axis.Y), min(24, W * 0.12))
        for side in (1, -1):
            for i in range(3):
                body = body - bd.Pos(-L * 0.2 + i * L * 0.2, 0, side * W / 2) * bd.Box(L * 0.12, H * 0.3, 8)
        skid = bd.Pos(0, -H / 2 + 3, 0) * _rounded_box(L * 0.9, 6, W * 0.9, 18)
        return [(body, "plastic", "#d9dcd5"), (skid, "plastic", "#5b6560")]
    if variant == "rover-alu-chassis":
        body = bd.Box(L, H, W)
        body = _safe_fillet(body, body.edges().filter_by(bd.Axis.Y), min(40, W * 0.1))
        skirt = bd.Pos(0, -H / 2 + H * 0.15, 0) * _rounded_box(L + 6, H * 0.3, W + 6, min(42, W * 0.1))
        bay = bd.Pos(L / 2 + 0.5, H * 0.1, 0) * bd.Box(1.5, H * 0.4, W * 0.55)
        port = bd.Pos(-L / 2 - 1, H * 0.1, W * 0.3) * _cyl_x(8, 4)
        return [(body, "paint", "#eef0ef"), (skirt, "rubber", "#2a2d31"), (bay, "glass", "#101317"),
                (port, "metal", STEEL)]
    if variant == "rugged-tracked-hull":
        hull = bd.Box(L, H, W)
        hull = _safe_chamfer(hull, hull.edges().filter_by(bd.Axis.Z).group_by(bd.Axis.X)[-1]
                             .group_by(bd.Axis.Y)[-1], H * 0.45)
        skid = bd.Pos(0, -H / 2 - 2, 0) * bd.Box(L * 0.92, 4, W * 0.85)
        pieces = [(hull, "paint", "#4b5a3f"), (skid, "metal", STEEL)]
        for x in (-L * 0.25, L * 0.15):  # grab handles
            pieces.append((bd.Pos(x, H / 2 + 9, 0) * _rounded_box(14, 18, W * 0.45, 4, bd.Axis.Z), "metal", DARK_ALU))
        for side in (1, -1):
            for i in range(6):
                pieces.append((bd.Pos(-L * 0.4 + i * L * 0.14, H * 0.25, side * (W / 2 + 0.8)) *
                               bd.Cylinder(3, 2), "metal", STEEL))
        return pieces
    if variant == "bench-base-plate":
        plate = bd.Box(L, H, W)
        plate = _safe_fillet(plate, plate.edges().filter_by(bd.Axis.Y), 8)
        for x in (-L / 2 + 18, 0, L / 2 - 18):
            for z in (-W / 2 + 18, W / 2 - 18):
                plate = plate - bd.Pos(x, H / 2, z) * _cyl_y(5.5, 8)
        pieces = [(plate, "metal", "#aeb4ba")]
        for x in (-L / 2 + 20, L / 2 - 20):
            for z in (-W / 2 + 20, W / 2 - 20):
                pieces.append((bd.Pos(x, -H / 2 - 3, z) * _cyl_y(9, 6), "rubber", RUBBER))
        return pieces
    return frame(L, H, W)


def motor_variant(r, h, variant=None) -> list[Piece]:
    if variant == "hub-motor-250w":
        shell = _cyl_y(r, h * 0.8)
        shell = _safe_fillet(shell, shell.edges(), min(6, h * 0.15))
        for i in range(8):
            a = math.radians(i * 45)
            shell = shell - bd.Pos(r * 0.72 * math.cos(a), h * 0.4, r * 0.72 * math.sin(a)) * _cyl_y(2.5, 6)
        axle = _cyl_y(r * 0.18, h * 1.2)
        cable = bd.Pos(r * 0.3, -h * 0.5, 0) * _cyl_y(3, h * 0.3)
        return [(shell, "paint", "#2d3034"), (axle, "metal", STEEL), (cable, "rubber", BLACK)]
    if variant == "maxon-dcx-gear":
        rr = r * 0.72
        can = bd.Pos(0, -h * 0.15, 0) * _cyl_y(rr, h * 0.6)
        head = bd.Pos(0, h * 0.3, 0) * _cyl_y(rr * 1.05, h * 0.3)
        cap = bd.Pos(0, -h * 0.47, 0) * _cyl_y(rr * 0.95, h * 0.06)
        band = bd.Pos(0, -h * 0.05, 0) * _cyl_y(rr + 0.3, h * 0.12)
        shaft = bd.Pos(0, h * 0.5 + 4, 0) * _cyl_y(2, 10)
        return [(can, "metal", "#c9cdd2"), (head, "metal", "#9ea4ab"), (cap, "plastic", BLACK),
                (band, "plastic", "#e8e8e6"), (shaft, "metal", STEEL)]
    if variant == "jgb37-gearmotor":
        can = bd.Pos(0, -h * 0.2, 0) * _cyl_y(r * 0.9, h * 0.55)
        gearbox = bd.Pos(0, h * 0.27, 0) * _cyl_y(r * 1.02, h * 0.38)
        tabs = bd.Pos(0, -h * 0.5, 0) * bd.Box(r * 0.8, 3, 3)
        shaft = bd.Pos(r * 0.3, h * 0.5 + 4, 0) * _cyl_y(3, 10)  # off-centre output shaft
        return [(can, "metal", "#b9bdc2"), (gearbox, "metal", "#c8a85e"), (tabs, "metal", "#d8b45a"),
                (shaft, "metal", STEEL)]
    if variant == "gobilda-5203-50to1":
        can = bd.Pos(0, -h * 0.22, 0) * _cyl_y(r * 0.95, h * 0.5)
        gearbox = bd.Pos(0, h * 0.25, 0) * _rounded_box(r * 2.1, h * 0.44, r * 2.1, 3)
        label = bd.Pos(0, -h * 0.22, 0) * _cyl_y(r * 0.95 + 0.3, h * 0.14)
        shaft = bd.Pos(0, h * 0.5 + 5, 0) * bd.Box(5.5, 12, 5.5)  # 6 mm D-shaft read as square
        encoder = bd.Pos(0, -h * 0.5 - 2, 0) * _cyl_y(r * 0.85, 4)
        return [(can, "metal", "#2a2c2f"), (gearbox, "metal", "#3a3d41"), (label, "plastic", "#f2c418"),
                (shaft, "metal", STEEL), (encoder, "plastic", BLACK)]
    # Pololu 37D with a magnetic encoder board on the back
    pieces = motor(r, h)
    pieces.append((bd.Pos(0, -h * 0.5 - 1, 0) * bd.Box(r * 2.1, 1.6, r * 2.1), "pcb", "#1d5b37"))
    pieces.append((bd.Pos(0, -h * 0.5 - 3, 0) * _cyl_y(r * 0.45, 2.5), "metal", DARK_ALU))
    return pieces


def battery_variant(L, H, W, variant=None) -> list[Piece]:
    if variant == "liion-4s-12ah":
        pack = bd.Box(L, H, W)
        pack = _safe_fillet(pack, pack.edges().filter_by(bd.Axis.X), min(H, W) / 2 - 0.6)
        lead = bd.Pos(L / 2 + 10, 0, 0) * bd.Box(20, 4, 4)
        xt60 = bd.Pos(L / 2 + 26, 0, 0) * bd.Box(12, 8, 16)
        balance = bd.Pos(L / 2 + 6, H * 0.2, W * 0.3) * bd.Box(10, 3, 8)
        return [(pack, "plastic", "#2f6db5"), (lead, "rubber", BLACK), (xt60, "plastic", "#e5c22b"),
                (balance, "plastic", "#ecebe6")]
    if variant == "lifepo4-24v-50ah":
        box = _rounded_box(L, H, W, 8)
        lid = bd.Pos(0, H / 2 - 6, 0) * _rounded_box(L + 2, 4, W + 2, 8)
        bms = bd.Pos(0, H * 0.1, W / 2 + 0.4) * bd.Box(L * 0.25, H * 0.2, 0.8)
        pieces: list[Piece] = [(box, "paint", "#5b6168"), (lid, "plastic", "#2c2f33"), (bms, "glass", "#0d1b2a")]
        for x, colour in ((L * 0.3, "#b33a2c"), (-L * 0.3, BLACK)):
            pieces.append((bd.Pos(x, H / 2 + 5, 0) * _cyl_y(7, 10), "plastic", colour))
        for end in (1, -1):
            pieces.append((bd.Pos(end * (L / 2 + 3), H * 0.2, 0) * _rounded_box(6, 14, W * 0.4, 3, bd.Axis.X),
                           "plastic", BLACK))
        return pieces
    if variant in ("lifepo4-12v-20ah", "lifepo4-12v-40ah"):
        box = _rounded_box(L, H, W, 4)
        stripe = bd.Pos(0, 0, W / 2 + 0.3) * bd.Box(L * 0.7, H * 0.18, 0.8)
        handle = bd.Pos(0, H / 2 + 6, 0) * bd.Box(L * 0.45, 12, 10) - bd.Pos(0, H / 2 + 4, 0) * bd.Box(L * 0.35, 9, 12)
        stripe_colour = "#3c8d5a" if variant == "lifepo4-12v-40ah" else "#2f6db5"
        return [(box, "plastic", "#1f2326"), (stripe, "plastic", stripe_colour), (handle, "plastic", "#2c2f33"),
                (bd.Pos(L * 0.36, H / 2 + 4, 0) * _cyl_y(5, 8), "plastic", "#b33a2c"),
                (bd.Pos(-L * 0.36, H / 2 + 4, 0) * _cyl_y(5, 8), "plastic", BLACK)]
    return battery(L, H, W)


def compute_variant(L, H, W, variant=None) -> list[Piece]:
    if variant in ("jetson-orin-nano", "jetson-orin-nx"):
        t, nx = 1.6, variant == "jetson-orin-nx"
        y0 = -H / 2 + t / 2
        board = bd.Pos(0, y0, 0) * bd.Box(L, t, W)
        sink_h = H - t - 4 if nx else H * 0.6
        sink = bd.Box(L * 0.62, sink_h, W * 0.7)
        for i in range(9):
            sink = sink - bd.Pos(-L * 0.28 + i * L * 0.07, sink_h * 0.2, 0) * bd.Box(L * 0.03, sink_h * 0.7, W * 0.75)
        sink = bd.Pos(-L * 0.1, y0 + t / 2 + 2 + sink_h / 2, 0) * sink
        fan = bd.Pos(-L * 0.1, y0 + t / 2 + 2 + sink_h + 1.5, 0) * _cyl_y(min(L, W) * 0.24, 3)
        pieces: list[Piece] = [(board, "pcb", "#1b2733"), (sink, "metal", "#3d4249" if nx else DARK_ALU),
                               (fan, "plastic", BLACK)]
        for i in range(4):  # USB-A stack, DP and RJ45 along the back edge
            pieces.append((bd.Pos(L / 2 - 7, y0 + t / 2 + 6, -W / 2 + 10 + i * (W - 20) / 3) *
                           bd.Box(14, 12, 13), "metal", STEEL))
        return pieces
    if variant == "raspberry-pi-5":
        pieces = compute(L, H, W)
        t = 1.6
        y0 = -H / 2 + t / 2
        pieces.append((bd.Pos(-6, y0 + t / 2 + 10, -2) * _cyl_y(10, 3), "plastic", BLACK))  # active cooler fan
        pieces.append((bd.Pos(-4, y0 + t / 2 + 5, -W / 2 + 4) * bd.Box(50, 7, 5), "plastic", BLACK))  # GPIO header
        return pieces
    return compute(L, H, W)


def camera_variant(D, H, W, variant=None) -> list[Piece]:
    if variant in ("realsense-d435", "zed-2i"):
        zed = variant == "zed-2i"
        body = bd.Box(D, H, W)
        body = _safe_fillet(body, body.edges().filter_by(bd.Axis.X), H / 2 - 0.6)  # stadium ends
        glass = bd.Pos(D / 2 + 0.3, 0, 0) * bd.Box(0.8, H * 0.72, W - H * 0.4)
        pieces: list[Piece] = [(body, "paint" if zed else "metal", "#25282c" if zed else "#a7adb3"),
                               (glass, "glass", "#0b0d10")]
        lenses = ((-W * 0.34, H * 0.3), (W * 0.34, H * 0.3)) if zed else \
            ((-W * 0.36, H * 0.15), (-W * 0.1, H * 0.1), (W * 0.12, H * 0.15), (W * 0.32, H * 0.17))
        for z, rr in lenses:
            pieces.append((bd.Pos(D / 2 + 1.2, 0, z) * _cyl_x(rr + 1.2, 1.6), "metal", "#8c9298" if zed else DARK_ALU))
            pieces.append((bd.Pos(D / 2 + 1.8, 0, z) * _cyl_x(rr, 1.2), "glass", GLASS))
        pieces.append((bd.Pos(0, -H / 2 - 1.5, 0) * _cyl_y(6, 3), "metal", STEEL))  # tripod mount
        return pieces
    if variant == "oak-d-lite":
        pieces = camera(D, H, W)
        for i in range(4):  # rear cooling fins
            pieces.append((bd.Pos(-D / 2 - 1.5, -H * 0.3 + i * H * 0.2, 0) * bd.Box(3, 2, W * 0.7), "metal", DARK_ALU))
        return pieces
    return camera(D, H, W)


def lidar_variant(r, h, variant=None) -> list[Piece]:
    if variant == "rplidar-a1":
        base = bd.Pos(0, -h * 0.35, 0) * bd.Box(2.2 * r, h * 0.25, 2 * r)
        base = _safe_fillet(base, base.edges().filter_by(bd.Axis.Y), 6)
        head = bd.Pos(r * 0.25, h * 0.05, 0) * _cyl_y(r * 0.62, h * 0.5)
        head = _safe_fillet(head, head.edges(), 2)
        window = bd.Pos(r * 0.25, h * 0.08, 0) * _cyl_y(r * 0.64, h * 0.18)
        drive = bd.Pos(-r * 0.7, -h * 0.12, 0) * _cyl_y(r * 0.22, h * 0.25)
        return [(base, "plastic", "#1d1f22"), (head, "plastic", "#2a2c2f"), (window, "glass", "#58201f"),
                (drive, "metal", STEEL)]
    return lidar(r, h)


def servo_variant(x, y, z, variant=None) -> list[Piece]:
    if variant and variant.startswith("dynamixel"):
        t = z * 0.56
        body = bd.Box(x, y, t)
        body = _safe_fillet(body, body.edges(), 2.5)
        for side in (1, -1):  # side ribs
            for i in range(3):
                body = body - bd.Pos(side * x / 2, -y * 0.25 + i * y * 0.18, 0) * bd.Box(2, 2, t * 0.8)
        horn = bd.Pos(0, y * 0.22, t / 2 + 1.6) * bd.Cylinder(9, 3.2)
        for i in range(4):
            a = math.radians(i * 90 + 45)
            horn = horn - bd.Pos(6 * math.cos(a), y * 0.22 + 6 * math.sin(a), t / 2 + 1.6) * bd.Cylinder(1, 4)
        idler = bd.Pos(0, y * 0.22, -t / 2 - 1) * bd.Cylinder(7, 2)
        return [(body, "plastic", "#2f3236"), (horn, "plastic", "#16181a"), (idler, "plastic", "#16181a")]
    pieces = servo(x, y, z)
    if variant == "feetech-sts3250":  # metal mid-case on the higher-torque model
        t = z * 0.56
        pieces[0] = (pieces[0][0], "plastic", "#18202b")
        pieces.append((bd.Pos(0, -y * 0.1, 0) * bd.Box(x + 0.6, y * 0.3, t + 0.6), "metal", DARK_ALU))
    return pieces


def gripper_variant(x, y, z, variant=None) -> list[Piece]:
    if variant == "printed-parallel-gripper":
        palm = _rounded_box(x, y, z, 4)
        rail = bd.Pos(0, -y / 2 - 2, 0) * bd.Box(x * 0.5, 4, z * 0.9)
        return [(palm, "plastic", "#e8e6df"), (rail, "metal", STEEL)]
    if variant == "alu-servo-gripper":
        palm = bd.Box(x, y, z)
        palm = _safe_fillet(palm, palm.edges().filter_by(bd.Axis.Y), 3)
        drive = bd.Pos(0, y / 2 + 6, 0) * _rounded_box(x * 0.8, 12, z * 0.45, 2)
        return [(palm, "metal", "#b7bcc2"), (drive, "plastic", "#1c1f22")]
    return gripper(x, y, z)


def finger_variant(x, y, z, variant=None) -> list[Piece]:
    if variant == "alu-servo-gripper":
        claw = bd.Box(x, y, z)
        claw = _safe_fillet(claw, claw.edges().filter_by(bd.Axis.Z), min(x, y) * 0.3)
        for i in range(3):  # serrated grip face
            claw = claw - bd.Pos(0, -y * 0.35 + i * y * 0.12, z / 2) * bd.Box(x + 2, 1.2, 1.6)
        return [(claw, "metal", "#b7bcc2")]
    if variant == "printed-parallel-gripper":
        body = bd.Box(x, y, z)
        body = _safe_fillet(body, body.edges().filter_by(bd.Axis.Z), min(x, y) * 0.3)
        pad = bd.Pos(0, -y * 0.25, 0) * bd.Box(x * 0.9, y * 0.45, z + 1.2)
        return [(body, "plastic", "#ecebe5"), (pad, "rubber", "#2a2c2e")]
    return finger(x, y, z)


def round_body_variant(r, h, variant=None) -> list[Piece]:
    if variant == "printed-petg-chassis":
        shell = _cyl_y(r, h)
        shell = _safe_fillet(shell, shell.edges(), min(6, h * 0.2))
        for i in range(6):
            a = math.radians(150 + i * 12)
            shell = shell - bd.Pos(r * math.cos(a), 0, r * math.sin(a)) * bd.Box(6, h * 0.35, 4)
        lid = bd.Pos(0, h / 2 + 0.6, 0) * _cyl_y(r * 0.7, 1.2)
        return [(shell, "plastic", "#cfd3cc"), (lid, "plastic", "#5b6560")]
    if variant == "abs-round-shell":
        pieces = round_body(r, h)
        seam = bd.Pos(0, h * 0.15, 0) * (_cyl_y(r + 0.4, 1.2) - _cyl_y(r - 2, 2))
        return [(pieces[0][0], "paint", "#f4f4f2"), pieces[1], (seam, "plastic", "#9aa0a6")]
    return round_body(r, h)


def _plain(fn):
    return lambda size, variant=None: fn(*size)


def _varied(fn):
    return lambda size, variant=None: fn(*size, variant=variant)


BUILDERS: dict[str, Callable[..., list[Piece]]] = {
    **{role: _plain(fn) for role, fn in {
        "deck": deck, "caster": caster, "mast": mast, "mic": mic, "turntable": turntable, "link": link,
        "wrist": wrist}.items()},
    **{role: _varied(fn) for role, fn in {
        "frame": frame_variant, "motor": motor_variant, "battery": battery_variant, "compute": compute_variant,
        "camera": camera_variant, "lidar": lidar_variant, "servo": servo_variant, "gripper": gripper_variant,
        "finger": finger_variant,
        "wheel": wheel_variant, "track": track, "round_body": round_body_variant, "round_bumper": round_bumper,
        "dust_bin": dust_bin, "side_brush": side_brush, "cargo_bin": cargo_bin, "lights": lights, "flag": flag,
        "enclosure": enclosure, "pan_tilt": pan_tilt, "tower": tower, "amr_body": amr_body, "lift_plate": lift_plate,
        "lift_column": lift_column, "estop": estop, "display": display, "speaker": speaker,
        "button": button}.items()},
}
CUSTOM_COLORS = {"petg": "#dfe2dc", "pla": "#e6e1d6", "aluminum": ALU}


def custom(spec: dict) -> list[Piece]:
    part = PartSpec.model_validate(spec)
    shape = bd.Rot(-90, 0, 0) * build_part(part)  # template Z-up -> Y-up, like its GLB export
    centre = shape.bounding_box().center()
    shape = bd.Pos(-centre.X, -centre.Y, -centre.Z) * shape
    finish = "metal" if part.material == "aluminum" else "plastic"
    return [(shape, finish, CUSTOM_COLORS[part.material])]


def _pieces(node: dict, cache: dict) -> list[Piece]:
    """Build a node's detailed parts once per (role, size, variant); repeats reuse the B-rep."""
    import json
    role = node.get("role", "other")
    size = [round(v * 1000, 2) for v in node.get("size", [])]
    key = json.dumps([role, size, node.get("variant"), node.get("spec")], sort_keys=True)
    if key not in cache:
        if node.get("spec"):
            cache[key] = custom(node["spec"])
        elif role in BUILDERS and size:
            cache[key] = BUILDERS[role](size, node.get("variant"))
        else:
            cache[key] = generic(*(size if len(size) == 3 else [50, 30, 50]))
    return cache[key]


def build_robot(nodes: list[dict]):
    """Return a labelled, coloured Z-up compound for STEP/GLB export."""
    children, cache = [], {}
    for index, node in enumerate(nodes):
        rx, ry, rz = (math.degrees(a) for a in node.get("rotation", [0, 0, 0]))
        gx, gy, gz = (math.degrees(a) for a in node.get("glb_rotation", [0, 0, 0]))
        px, py, pz = (v * 1000 for v in node["position"])
        place = bd.Pos(px, py, pz) * bd.Rot(rx, ry, rz) * bd.Rot(gx, gy, gz)
        for sub, (shape, finish, hex_color) in enumerate(_pieces(node, cache)):
            solid = place * shape  # placed copy; the cached source shape is not modified
            # Name carries role, finish and component id for the viewer and picking.
            solid.label = f"{node.get('role', 'other')}.{finish}__{node.get('component_id') or 'none'}__{index}_{sub}"
            red, green, blue = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
            solid.color = bd.Color(red, green, blue, 1.0)
            children.append(solid)
    robot = bd.Compound(children=children, label="robot")
    return bd.Rot(90, 0, 0) * robot  # Y-up authoring frame -> Z-up CAD convention
