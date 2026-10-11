"""3D layout of the whole robot from its parts list, per body plan (archetype).

Units are metres, Y is up, the robot faces +X. Each node names a `role` that
roboforge/cad/robot.py turns into detailed CAD; `variant` (the catalog id)
selects the specific model, e.g. pneumatic vs mecanum wheels. Generated CAD
parts are placed as their exact geometry. This is a layout, not a checked
assembly (no interference, mounting or kinematic validation).
"""
from __future__ import annotations

import math

from pydantic import BaseModel

from roboforge.archetypes import ARCHETYPES
from roboforge.cad.spec import VENT_PITCH_MM, PartSpec
from roboforge.concept import Concept, to_archetype
from roboforge.models import Component, RobotProject

COLORS = {"frame": "#5f6f63", "deck": "#c6d8b6", "wheel": "#2d3a32", "motor": "#8a8f88", "battery": "#4f6273",
          "compute": "#345d49", "camera": "#26302a", "arm": "#dfe7d6", "servo": "#3b4a40", "gripper": "#a94f27",
          "mic": "#8a958a", "mast": "#9aa596", "cover": "#dfe2dc", "other": "#b9c3b2"}
COMPUTE_SIZES = {"raspberry-pi-5": [0.085, 0.022, 0.056], "jetson-orin-nano": [0.10, 0.03, 0.079],
                 "jetson-orin-nx": [0.104, 0.036, 0.09]}
CAMERA_SIZES = {"oak-d-lite": [0.03, 0.028, 0.091], "realsense-d435": [0.025, 0.025, 0.09],
                "zed-2i": [0.032, 0.031, 0.175]}
WHEEL_WIDTH = {65: 0.026, 100: 0.04, 150: 0.055}
BATTERY_SIDE_LEAD_MM = {"liion-4s-12ah": 34}  # XT60 lead out of the +X end of the pack model


class Node(BaseModel):
    id: str
    label: str
    component_id: str | None = None
    shape: str  # box | cylinder | sphere | glb (simplified preview shape)
    size: list[float] = []  # box [x,y,z]; cylinder [radius, height]; sphere [radius]
    position: list[float]
    rotation: list[float] = [0, 0, 0]  # XYZ Euler radians
    color: str = COLORS["other"]
    glb: str | None = None
    glb_rotation: list[float] = [0, 0, 0]
    role: str = "other"
    variant: str | None = None  # catalog id: selects the detailed model
    spec: dict | None = None    # PartSpec for generated CAD parts


class Assembly(BaseModel):
    robot_type: str
    archetype: str
    nodes: list[Node]
    summary: dict
    unplaced: list[str]
    notes: list[str]


def _infer_archetype(comps: list[Component]) -> str:
    kinds = {c.kind for c in comps}
    for kind, key in (("track", "tracked_explorer"), ("vacuum", "cleaning_robot"), ("lift", "warehouse_amr"),
                      ("cargo_bin", "delivery_rover"), ("display", "telepresence")):
        if kind in kinds:
            return key
    moving = "drive_motor" in kinds
    if "arm_servo" in kinds:
        return "mobile_manipulator" if moving else "stationary_arm"
    return "mobile_robot"


class _Layout:
    def __init__(self, project: RobotProject):
        self.project = project
        self.comps = project.components
        self.nodes: list[Node] = []
        self.placed: set[str] = set()
        self.cad: dict[str, dict] = {}
        for part in project.manufacturing.get("cad_parts", {}).values():
            self.cad[part["spec"]["kind"]] = part
        self.reach = 0.0
        self.mast_top: tuple[float, float] | None = None

    def first(self, kind: str) -> Component | None:
        return next((c for c in self.comps if c.kind == kind), None)

    def qty(self, kind: str) -> int:
        return sum(c.quantity for c in self.comps if c.kind == kind)

    def add(self, role: str, component: Component | None, shape: str, size, position, rotation=(0, 0, 0),
            label: str | None = None, **extra) -> None:
        self.nodes.append(Node(
            id=f"n{len(self.nodes)}", role=role, label=label or (component.name if component else role.replace("_", " ")),
            component_id=component.id if component else extra.pop("component_id", None), shape=shape,
            size=[round(v, 4) for v in size], position=[round(v, 4) for v in position],
            rotation=list(rotation), variant=component.catalog_id if component else None,
            color=COLORS.get(role, COLORS["other"]), **extra))
        if component:
            self.placed.add(component.id)

    def custom(self, kind: str, position, rotation=(0, 0, 0), glb_rotation=(0, 0, 0)) -> bool:
        part = self.cad.get(kind)
        if not part:
            return False
        self.nodes.append(Node(
            id=f"n{len(self.nodes)}", role="custom", label=part["spec"]["name"], component_id=part.get("component_id"),
            shape="glb", spec=part["spec"], position=[round(v, 4) for v in position], rotation=list(rotation),
            glb_rotation=list(glb_rotation), color=COLORS["deck"],
            glb=f"/projects/{self.project.id}/cad/{part['design_id']}/glb?revision={self.project.revision}"))
        if part.get("component_id"):
            self.placed.add(part["component_id"])
        return True

    # ---------------------------------------------------------------- shared modules
    def wheel_geometry(self) -> tuple[Component | None, float, float]:
        wheel = self.first("wheel")
        mm = int(wheel.specs.get("diameter_mm", 100)) if wheel else 120
        return wheel, mm / 2000, WHEEL_WIDTH.get(mm, 0.045)

    def arm(self, root_x: float, root_z: float, top: float, link_scale: float = 1.0) -> None:
        servos = [c for c in self.comps if c.kind == "arm_servo"]
        dof = sum(c.quantity for c in servos)
        if not dof:
            return
        joints = [c for c in servos for _ in range(c.quantity)]
        link_part = self.cad.get("arm_link")
        link_len = max(0.06, link_part["spec"]["length_mm"] / 1000) if link_part else 0.12 * link_scale
        self.add("turntable", joints[0], "cylinder", [0.03, 0.035], [root_x, top + 0.0175, root_z],
                 label="Arm base joint")
        segments = max(1, min(dof - 1, 3))
        angles = [math.radians(a) for a in (65, -10, -55)][:segments]
        lengths = [link_len, link_len if link_part else link_len * 0.9, 0.05][:segments]
        p = [root_x, top + 0.055, root_z]
        for i, (angle, ln) in enumerate(zip(angles, lengths)):
            joint = joints[min(i + 1, dof - 1)]
            k = 1 + max(0.0, joint.specs.get("torque_nm", 3) - 3) / 20
            self.add("servo", joint, "box", [0.034 * k, 0.046 * k, 0.05 * k], p, label=f"{joint.name} (arm joint)")
            end = [p[0] + ln * math.cos(angle), p[1] + ln * math.sin(angle), root_z]
            centre = [(p[0] + end[0]) / 2, (p[1] + end[1]) / 2, root_z]
            if not (i < 2 and self.custom("arm_link", centre, (0, 0, angle), (math.pi / 2, 0, 0))):
                self.add("link", joint, "box", [ln, 0.03, 0.02], centre, (0, 0, angle), label="Arm link")
            p = end
        for joint in joints[segments + 1:]:
            self.add("wrist", joint, "cylinder", [0.02, 0.03], p, (0, 0, math.pi / 2), label=f"{joint.name} (wrist)")
        gripper = self.first("gripper")
        if gripper:
            tip = [p[0], p[1] - 0.03, root_z]
            self.add("gripper", gripper, "box", [0.03, 0.02, 0.07], tip)
            for side in (1, -1):
                self.add("finger", gripper, "box", [0.012, 0.05, 0.01], [tip[0], tip[1] - 0.035, root_z + side * 0.025])
        self.reach = math.hypot(p[0] - root_x, p[1] - top)

    def camera_box(self, position, rotation=(0, 0, 0)) -> float:
        camera = self.first("camera")
        if not camera:
            return 0.0
        size = CAMERA_SIZES.get(camera.catalog_id, [0.03, 0.028, 0.10])
        self.add("camera", camera, "box", size, [position[0], position[1] + size[1] / 2, position[2]], rotation)
        return size[1]

    def lidar(self, position) -> None:
        lidar = self.first("lidar")
        if lidar:
            r, h = (0.039, 0.038) if lidar.catalog_id == "rplidar-s2" else (0.035, 0.055)
            self.add("lidar", lidar, "cylinder", [r, h], [position[0], position[1] + h / 2, position[2]])

    def mast_sensors(self, x: float, top: float, height: float) -> None:
        frame = self.first("frame")
        self.add("mast", None, "cylinder", [0.012, height], [x, top + height / 2, 0], label="Sensor mast",
                 component_id=frame.id if frame else None)
        self.mast_top = (x, top + height)
        pan = self.first("pan_tilt")
        if pan:
            self.add("pan_tilt", pan, "cylinder", [0.04, 0.07], [x, top + height + 0.035, 0])
            top += 0.07
        head = top + height + self.camera_box([x + 0.015, top + height, 0])
        mic = self.first("microphone")
        if mic:
            self.add("mic", mic, "cylinder", [0.035, 0.01], [x + 0.015, head + 0.005, 0])

    def mic_at(self, position) -> None:
        mic = self.first("microphone")
        if mic and mic.id not in self.placed:
            self.add("mic", mic, "cylinder", [0.035, 0.01], [position[0], position[1] + 0.005, position[2]])

    def hidden(self, kind: str, role: str, position, size=(0.06, 0.03, 0.06)) -> None:
        """Parts that live inside the body still get a node so they can be selected."""
        component = self.first(kind)
        if component:
            self.add(role, component, "box", list(size), position)

    def cover(self, kind: str, label: str) -> None:
        """Printed cover over a module on the open deck, sized to it with 4 mm clearance."""
        cover, module = self.first("cover"), next((n for n in self.nodes if n.role == kind), None)
        used = sum(1 for n in self.nodes if n.role == "cover")
        if not (cover and module) or used >= cover.quantity:
            return
        wall, gap, flange = 2.4, 4.0, 8.0
        sx, sy, sz = (v * 1000 for v in module.size)
        x, y, z = module.position
        if kind == "battery":  # room for terminals and cable lugs on top, and the +X side lead if the pack has one
            lead = BATTERY_SIDE_LEAD_MM.get(module.variant or "", 0)
            sy += 16
            sx += lead
            x += lead / 2000
        length, width, height = sx + 2 * (gap + wall), sz + 2 * (gap + wall), sy + gap + wall
        vents = 0 if kind == "battery" else min(8, int((length - 2 * wall - 14) // VENT_PITCH_MM) + 1)
        spec = PartSpec(kind="cover", name=label, length_mm=round(length, 1), width_mm=round(width, 1),
                        height_mm=round(height, 1), thickness_mm=wall, hole_diameter_mm=3.4,
                        hole_inset_mm=flange / 2, vent_slots=vents, material="petg")
        deck = y - module.size[1] / 2
        self.add("cover", cover, "box", [(spec.length_mm + 2 * flange) / 1000, spec.height_mm / 1000,
                                         (spec.width_mm + 2 * flange) / 1000],
                 [x, deck + spec.height_mm / 2000, z], label=label, spec=spec.model_dump())

    def extras(self) -> None:
        """Modules the AI concept added that this body plan doesn't place itself."""
        tops = [n.position[1] + n.size[1] / 2 for n in self.nodes
                if n.role in ("frame", "deck", "amr_body", "round_body", "lift_plate") and len(n.size) > 1]
        top = max(tops, default=0.1)
        length, width = self.footprint
        front = length / 2
        frame = self.first("frame")
        for kind in ("cargo_bin", "display", "speaker", "lights", "proximity", "pan_tilt"):
            c = self.first(kind)
            if not c or c.id in self.placed:
                continue
            if kind == "cargo_bin":
                h = 0.2
                self.add("cargo_bin", c, "box", [length * 0.45, h, width * 0.7], [-length * 0.2, top + h / 2, 0])
            elif kind == "display":
                if self.mast_top:
                    x, y = self.mast_top
                    self.add("display", c, "box", [0.03, 0.11, 0.17], [x + 0.03, y - 0.12, 0], (0, 0, -0.12))
                else:
                    self.add("mast", None, "cylinder", [0.01, 0.16], [front - 0.08, top + 0.08, 0], label="Screen post",
                             component_id=frame.id if frame else None)
                    self.add("display", c, "box", [0.03, 0.11, 0.17], [front - 0.06, top + 0.2, 0], (0, 0, -0.2))
            elif kind == "speaker":
                if self.mast_top:
                    x, y = self.mast_top
                    self.add("speaker", c, "box", [0.03, 0.06, 0.07], [x + 0.03, y * 0.55, 0])
                else:
                    self.add("speaker", c, "box", [0.05, 0.04, 0.07], [-front + 0.06, top + 0.02, width / 4])
            elif kind == "lights":
                self.add("lights", c, "box", [0.012, 0.022, width * 0.6], [front + 0.006, top - 0.03, 0])
            elif kind == "proximity":
                self.add("bumper", c, "box", [0.015, 0.03, width * 0.8], [front + 0.012, 0.06, 0], label=c.name)
            elif kind == "pan_tilt":
                self.add("pan_tilt", c, "cylinder", [0.04, 0.07], [front - 0.06, top + 0.035, -width / 4])

    # ---------------------------------------------------------------- body plans
    def rect(self, arch) -> None:
        frame = self.first("frame")
        length, width = arch.size_m
        plate = self.cad.get("chassis_plate")
        if plate and arch.key != "tracked_explorer":
            length = max(0.18, plate["spec"]["length_mm"] / 1000)
            width = max(0.14, plate["spec"]["width_mm"] / 1000)
        body_h = arch.body_h_m
        if arch.track:
            track = self.first("track")
            th = 0.13
            bottom = 0.05
            for side in (1, -1):
                self.add("track", track, "box", [length * 1.08, th, 0.075], [0, th / 2, side * (width / 2 + 0.04)])
            motor = self.first("drive_motor")
            for side in (1, -1):
                self.add("motor", motor, "cylinder", [0.022, 0.07], [-length * 0.42, 0.075, side * (width / 2 - 0.03)],
                         (math.pi / 2, 0, 0))
        else:
            wheel, r, w = self.wheel_geometry()
            bottom = max(0.03, r * 0.55)
            count = self.qty("wheel") or self.qty("drive_motor")
            xs = [0.0] if count <= 2 else [length * 0.32, -length * 0.32]
            motor = self.first("drive_motor")
            for x in xs:
                for side in (1, -1):
                    self.add("wheel", wheel or motor, "cylinder", [r, w], [x, r, side * (width / 2 + w / 2 + 0.008)],
                             (math.pi / 2, 0, 0), label=(wheel or motor).name if (wheel or motor) else "Wheel")
                    if motor:
                        self.add("motor", motor, "cylinder", [0.018, 0.07], [x, r, side * (width / 2 - 0.035)],
                                 (math.pi / 2, 0, 0))
                    self.custom("motor_bracket", [x, bottom - 0.002, side * (width / 2 - 0.05)], (math.pi, 0, 0))
            if count <= 2:
                for x in (length / 2 - 0.05, -length / 2 + 0.05):
                    self.add("caster", None, "sphere", [0.018], [x, 0.018, 0], label="Caster",
                             component_id=frame.id if frame else None)
        top = bottom + body_h
        self.add("frame", frame, "box", [length, body_h, width], [0, bottom + body_h / 2, 0])
        if not (plate and arch.key != "tracked_explorer" and self.custom(
                "chassis_plate", [0, top + plate["spec"]["thickness_mm"] / 2000, 0])):
            deck_spec = None
            if arch.key not in ("delivery_rover", "tracked_explorer"):
                deck_spec = PartSpec(kind="chassis_plate", name="Deck plate",
                                     length_mm=round((length - 0.01) * 1000, 1),
                                     width_mm=round((width - 0.01) * 1000, 1), thickness_mm=6,
                                     hole_diameter_mm=4.4, hole_inset_mm=12, material="petg").model_dump()
            self.add("deck", None, "box", [length - 0.01, 0.006, width - 0.01], [0, top + 0.003, 0],
                     label="Deck plate", component_id=frame.id if frame else None, spec=deck_spec)
        top += plate["spec"]["thickness_mm"] / 1000 if plate and arch.key != "tracked_explorer" else 0.006

        if arch.key == "delivery_rover":
            self.hidden("battery", "battery", [-length * 0.2, bottom + body_h / 2, 0], (0.17, 0.08, 0.1))
            self.hidden("compute", "compute", [length * 0.15, bottom + body_h / 2, 0], (0.1, 0.03, 0.08))
            bin_c = self.first("cargo_bin")
            bin_h = (0.34 if bin_c.specs.get("volume_l", 18) >= 30 else 0.28) if bin_c else 0.0
            bl, bw = length * 0.8, width * 0.94
            bx = -length * 0.08
            if bin_c:
                self.add("cargo_bin", bin_c, "box", [bl, bin_h, bw], [bx, top + bin_h / 2, 0])
            pan = self.first("pan_tilt")
            if pan:
                self.add("pan_tilt", pan, "cylinder", [0.04, 0.07], [bx + bl / 2 - 0.02, top + bin_h + 0.035, width / 4])
            self.camera_box([bx + bl / 2 + 0.012, top + bin_h - 0.06, 0])
            self.lidar([bx + bl / 2 - 0.07, top + bin_h, 0])
            self.mic_at([bx + bl / 2 - 0.16, top + bin_h, 0])
            lights = self.first("lights")
            for end in (1, -1) if lights else ():
                self.add("lights", lights, "box", [0.012, 0.022, width * 0.7], [end * (length / 2 + 0.006), bottom + body_h * 0.65, 0])
            self.add("flag", None, "cylinder", [0.005, 0.75], [-length / 2 + 0.04, top + 0.375, width / 2 - 0.04],
                     label="Safety flag", component_id=frame.id if frame else None)
        elif arch.key == "tracked_explorer":
            self.hidden("battery", "battery", [-length * 0.1, bottom + body_h / 2, 0], (0.17, 0.08, 0.1))
            compute = self.first("compute")
            if compute:
                size = COMPUTE_SIZES.get(compute.catalog_id, [0.10, 0.03, 0.079])
                self.add("compute", compute, "box", size, [-length * 0.12, top + size[1] / 2, 0])
                self.cover("compute", "Computer cover")
            self.mic_at([-length * 0.2, top + 0.09, width * 0.15])
            pan = self.first("pan_tilt")
            dof = self.qty("arm_servo")
            px, pz = (length / 2 - 0.08, (-width / 4 if dof else 0))
            if pan:
                self.add("pan_tilt", pan, "cylinder", [0.04, 0.07], [px, top + 0.035, pz])
                self.camera_box([px, top + 0.07, pz])
            else:
                self.camera_box([px, top, pz])
            self.lidar([-length / 2 + 0.06, top + 0.09, 0])
            lights = self.first("lights")
            if lights:
                self.add("lights", lights, "box", [0.012, 0.022, width * 0.6], [length / 2 + 0.006, bottom + body_h * 0.7, 0])
            if dof:
                self.arm(length * 0.08, width / 5, top)
        else:  # mobile manipulator / mobile robot
            battery = self.first("battery")
            if battery:
                h = 0.06 + battery.specs.get("capacity_wh", 150) / 5000
                self.add("battery", battery, "box", [0.17, h, 0.09], [-length / 2 + 0.11, top + h / 2, -width / 4])
            compute = self.first("compute")
            if compute:
                size = COMPUTE_SIZES.get(compute.catalog_id, [0.09, 0.025, 0.065])
                self.add("compute", compute, "box", size, [-length / 2 + 0.11, top + size[1] / 2, width / 4])
            self.cover("battery", "Battery cover")
            self.cover("compute", "Computer cover")
            self.mast_sensors(-length / 2 + 0.035, top, arch.mast_m or 0.35)
            dof = self.qty("arm_servo")
            self.lidar([length / 2 - 0.06, top, -width / 2 + 0.06 if dof else 0])
            self.arm(length / 2 - 0.09, 0, top)
        self.footprint = [length, width + (0.15 if arch.track else 0.12)]

    def low(self, arch) -> None:
        frame = self.first("frame")
        length, width = arch.size_m
        wheel, r, w = self.wheel_geometry()
        motor = self.first("drive_motor")
        bottom, body_h = 0.03, arch.body_h_m
        for x in (length * 0.3, -length * 0.3):
            for side in (1, -1):
                self.add("wheel", wheel, "cylinder", [r, w], [x, r, side * (width / 2 - 0.08)], (math.pi / 2, 0, 0))
                if motor:
                    self.add("motor", motor, "cylinder", [0.045, 0.06], [x, r, side * (width / 2 - 0.14)],
                             (math.pi / 2, 0, 0))
        self.add("amr_body", frame, "box", [length, body_h, width], [0, bottom + body_h / 2, 0])
        top = bottom + body_h
        self.hidden("battery", "battery", [-length * 0.15, bottom + body_h / 2, 0], (0.3, 0.1, 0.16))
        self.hidden("compute", "compute", [length * 0.15, bottom + body_h / 2, 0], (0.1, 0.03, 0.08))
        lift = self.first("lift")
        gap = 0.03
        for x in (length * 0.3, -length * 0.3):
            for z in (width * 0.3, -width * 0.3):
                self.add("lift_column", lift, "cylinder", [0.022, gap + 0.01], [x, top + gap / 2, z])
        self.add("lift_plate", lift, "box", [length * 0.92, 0.022, width * 0.92], [0, top + gap + 0.011, 0])
        self.lidar([length / 2 - 0.035, bottom + 0.03, 0])
        self.camera_box([length / 2 + 0.012, bottom + body_h * 0.55, 0])
        lights = self.first("lights")
        for end in (1, -1):
            self.add("lights", lights, "box", [0.01, 0.018, width * 0.8], [end * (length / 2 + 0.005), bottom + body_h * 0.85, 0])
        self.add("estop", None, "cylinder", [0.02, 0.025], [-length / 2 + 0.06, top + gap + 0.035, width / 2 - 0.06],
                 label="Emergency stop", component_id=frame.id if frame else None)
        self.mic_at([-length / 2 + 0.06, top + gap + 0.022, -width / 2 + 0.06])
        self.footprint = [length, width]

    def round(self, arch) -> None:
        frame = self.first("frame")
        radius = arch.size_m[0] / 2
        wheel, r, w = self.wheel_geometry()
        motor = self.first("drive_motor")
        bottom = 0.012 if arch.key == "cleaning_robot" else 0.03
        body_h = arch.body_h_m
        for side in (1, -1):
            self.add("wheel", wheel, "cylinder", [r, w], [0, r, side * (radius - 0.045)], (math.pi / 2, 0, 0))
            if motor:
                self.add("motor", motor, "cylinder", [0.016, 0.05], [0, r, side * (radius - 0.09)], (math.pi / 2, 0, 0))
        self.add("round_body", frame, "cylinder", [radius, body_h], [0, bottom + body_h / 2, 0])
        top = bottom + body_h
        self.hidden("battery", "battery", [-radius * 0.35, bottom + body_h / 2, 0], (0.12, 0.04, 0.08))
        self.hidden("compute", "compute", [radius * 0.25, bottom + body_h / 2, 0], (0.09, 0.02, 0.06))
        if arch.key == "cleaning_robot":
            self.add("round_bumper", self.first("proximity"), "cylinder", [radius + 0.005, body_h * 0.7],
                     [0, bottom + body_h * 0.45, 0])
            vac = self.first("vacuum")
            self.add("dust_bin", vac, "box", [0.1, 0.012, radius * 1.1], [-radius * 0.62, top + 0.004, 0])
            brush = self.first("side_brush")
            for side in (1, -1):
                self.add("side_brush", brush, "cylinder", [0.05, 0.006], [radius * 0.6, 0.006, side * radius * 0.55])
            self.lidar([-radius * 0.1, top, 0])
            self.camera_box([radius - 0.005, top - 0.035, 0])
            self.add("button", None, "cylinder", [0.018, 0.006], [radius * 0.45, top + 0.003, 0], label="Start button",
                     component_id=frame.id if frame else None)
            self.mic_at([radius * 0.15, top, radius * 0.45])
        elif arch.key == "security_patrol":
            self.lidar([radius * 0.6, top, 0])
            tower_h, tx = arch.mast_m or 0.7, -radius * 0.1
            self.add("tower", None, "cylinder", [0.045, tower_h], [tx, top + tower_h / 2, 0], label="Sensor tower",
                     component_id=frame.id if frame else None)
            speaker = self.first("speaker")
            if speaker:
                self.add("speaker", speaker, "box", [0.03, 0.06, 0.07], [tx + 0.058, top + tower_h * 0.45, 0])
            lights = self.first("lights")
            if lights:
                self.add("lights", lights, "box", [0.012, 0.022, 0.08], [tx + 0.051, top + tower_h * 0.8, 0])
            pan = self.first("pan_tilt")
            head = top + tower_h
            if pan:
                self.add("pan_tilt", pan, "cylinder", [0.04, 0.07], [tx, head + 0.035, 0])
                head += 0.07
            self.camera_box([tx + 0.01, head, 0])
            self.mic_at([tx - 0.03, top, radius * 0.4])
        else:  # telepresence
            self.lidar([radius * 0.55, top, 0])
            mast_h = arch.mast_m or 0.95
            self.add("mast", None, "cylinder", [0.022, mast_h], [-radius * 0.1, top + mast_h / 2, 0], label="Neck",
                     component_id=frame.id if frame else None)
            head_y = top + mast_h
            display = self.first("display")
            dw, dh = (0.25, 0.16) if display and display.specs.get("diagonal_in", 7) > 8 else (0.17, 0.11)
            self.add("display", display, "box", [0.03, dh, dw], [-radius * 0.1 + 0.02, head_y + dh / 2, 0],
                     (0, 0, -0.12))
            speaker = self.first("speaker")
            if speaker:
                self.add("speaker", speaker, "box", [0.04, 0.05, dw * 0.8], [-radius * 0.1, head_y - 0.04, 0])
            cam_h = self.camera_box([-radius * 0.1 + 0.02, head_y + dh + 0.004, 0])
            mic = self.first("microphone")
            if mic:
                self.add("mic", mic, "cylinder", [0.03, 0.01], [-radius * 0.1, head_y + dh + cam_h + 0.01, 0])
        self.footprint = [radius * 2, radius * 2]

    def plate(self, arch) -> None:
        frame = self.first("frame")
        length, width = arch.size_m
        self.add("frame", frame, "box", [length, arch.body_h_m, width], [0, arch.body_h_m / 2, 0], label=(
            f"{frame.name} (bench base)" if frame else "Bench base"))
        top = arch.body_h_m
        compute = self.first("compute")
        if compute:
            size = COMPUTE_SIZES.get(compute.catalog_id, [0.09, 0.025, 0.065])
            self.add("compute", compute, "box", size, [-length / 2 + 0.07, top + size[1] / 2, width / 2 - 0.06])
            self.cover("compute", "Computer cover")
        post_h = 0.38
        self.add("mast", None, "cylinder", [0.012, post_h], [-length / 2 + 0.04, top + post_h / 2, -width / 2 + 0.05],
                 label="Camera post", component_id=frame.id if frame else None)
        self.camera_box([-length / 2 + 0.07, top + post_h, -width / 2 + 0.05])
        self.mic_at([length / 2 - 0.05, top, -width / 2 + 0.05])
        self.arm(0.02, 0, top, link_scale=1.25)
        self.footprint = [length, width]


def build_assembly(project: RobotProject) -> Assembly:
    layout = _Layout(project)
    key = (project.architecture or {}).get("archetype") or _infer_archetype(project.components)
    concept = None if project.requirements.robot_type else (project.architecture or {}).get("concept")
    arch = to_archetype(Concept.model_validate(concept)) if concept and concept.get("chassis") == key else \
        ARCHETYPES.get(key, ARCHETYPES["mobile_robot"])
    {"rect": layout.rect, "low": layout.low, "round": layout.round, "plate": layout.plate}[arch.base](arch)
    layout.extras()

    # Anything else (e.g. parts added by hand) sits on top in a row.
    tops = [n.position[1] + (n.size[1] / 2 if len(n.size) > 1 else 0) for n in layout.nodes
            if n.role in ("frame", "deck", "amr_body", "round_body", "lift_plate")]
    deck = max(tops, default=0.1)
    loose = [c for c in project.components if c.id not in layout.placed and c.kind not in ("wiring",)]
    for i, c in enumerate(loose):
        layout.add("other", c, "box", [0.05, 0.03, 0.05], [-0.02 + (i % 3) * 0.06, deck + 0.015, -0.06 + (i // 3) * 0.06])

    nodes = layout.nodes
    height = max((n.position[1] + (n.size[1] if len(n.size) > 1 else n.size[0] if n.size else 0) / 2
                  for n in nodes), default=0)
    wheel_nodes = sum(1 for n in nodes if n.role == "wheel")
    wiring = layout.first("wiring")
    return Assembly(
        robot_type=(project.architecture or {}).get("type") or arch.label,
        archetype=arch.key,
        nodes=nodes,
        summary={"wheels": "Tracks" if arch.track else wheel_nodes, "arm_joints": layout.qty("arm_servo"),
                 "footprint_m": [round(v, 3) for v in layout.footprint], "height_m": round(height, 3),
                 "arm_reach_m": round(layout.reach, 3), "generated_parts_used": sorted(layout.cad),
                 "body_plan": arch.label},
        unplaced=[wiring.name] if wiring else [],
        notes=["Layout from the parts list; not an interference- or fit-checked assembly.",
               "Catalog parts are representative models. Generated CAD parts are their real exported geometry."],
    )
