"""How to build the robot: printable parts, step-by-step assembly and a wiring table.

Electrical sizing comes from catalog power ratings: current = power / voltage, motors
sized for 2x their rated current while accelerating. Fuses are the next standard size
above 1.25x the expected current and every wire is rated for at least its fuse, so a
fault blows the fuse before the wire overheats. These are screening values; check
them against each part's datasheet before wiring.
"""
from __future__ import annotations

import math
import re

from roboforge.assembly import Assembly, Node, build_assembly
from roboforge.cad.spec import PartSpec
from roboforge.models import Component, RobotProject

BED_MM = (220, 220, 250)  # common desktop printer (Prusa MK4 / Ender-3 class)
DENSITY_G_MM3 = {"petg": 1.27e-3, "pla": 1.24e-3}
GRAMS_PER_HOUR = 12       # 0.4 mm nozzle, 0.2 mm layers
# Silicone-insulated copper, short runs in free air.
AMPACITY = [(22, 5), (20, 7.5), (18, 10), (16, 15), (14, 20), (12, 30), (10, 40), (8, 55), (6, 75), (4, 95),
            (2, 130)]
FUSES = [1, 2, 3, 5, 7.5, 10, 15, 20, 25, 30, 40, 50, 60, 80, 100]
MOTOR_V = {"hub-motor-250w": 24.0}  # every other drive motor in the catalog is a 12 V gearmotor
SERVO_V = {"dynamixel-xm430": (12, 14.8), "dynamixel-xm540": (12, 14.8),
           "feetech-sts3250": (12, 12.6), "feetech-sts3215": (7.4, 8.4)}  # (nominal, max)
TOOLS = ["Metric hex keys 1.5-5 mm and Phillips #1/#2 drivers",
         "Wire stripper, ratcheting crimper for XT and JST contacts, ferrules",
         "Multimeter (set every converter's output before connecting anything to it)",
         "Soldering iron, heat-shrink tubing and a heat-set insert tip",
         "Medium-strength threadlocker and cable ties"]

ROLE_STEP = {
    "frame": "frame", "deck": "frame", "amr_body": "frame", "round_body": "frame", "caster": "frame", "flag": "frame",
    "wheel": "drive", "motor": "drive", "track": "drive",
    "battery": "power",
    "compute": "electronics", "enclosure": "electronics", "estop": "electronics", "button": "electronics",
    "camera": "sensors", "lidar": "sensors", "mic": "sensors", "mast": "sensors", "tower": "sensors",
    "pan_tilt": "sensors", "display": "sensors", "speaker": "sensors", "lights": "sensors", "bumper": "sensors",
    "round_bumper": "sensors",
    "turntable": "arm", "servo": "arm", "link": "arm", "wrist": "arm", "gripper": "arm", "finger": "arm",
    "cover": "covers",
}
CUSTOM_STEP = {"chassis_plate": "frame", "motor_bracket": "drive", "arm_link": "arm"}


def _fuse(amps: float) -> float:
    return next((f for f in FUSES if f >= amps * 1.25), FUSES[-1])


def _gauge(amps: float) -> int:
    return next((g for g, limit in AMPACITY if limit >= amps), AMPACITY[-1][0])


def _connector(amps: float) -> str:
    return ("JST-VH 2-pin" if amps <= 3 else "XT30" if amps <= 15 else "XT60" if amps <= 30
            else "XT90" if amps <= 40 else "Anderson SB50")


def _power(src: str, dst: str, volts: float, amps: float, note: str = "", fused: bool = True) -> dict:
    fuse = _fuse(amps) if fused else None
    rated = fuse or amps * 1.25
    return {"from": src, "to": dst, "type": "power", "voltage": f"{volts:g} V DC", "current_a": round(amps, 1),
            "wire": f"{_gauge(rated)} AWG, red (+) / black (−)", "connector": _connector(rated),
            "fuse_a": fuse, "note": note}


def _data(src: str, dst: str, signal: str, cable: str, note: str = "") -> dict:
    return {"from": src, "to": dst, "type": "data", "voltage": signal, "current_a": None, "wire": cable,
            "connector": "", "fuse_a": None, "note": note}


def pack_voltage(battery: Component) -> tuple[float, float]:
    """Nominal and fully charged voltage, from the cell chemistry and count in the battery name."""
    lfp = "lifepo4" in battery.name.lower()
    nominal, full = (3.2, 3.65) if lfp else (3.7, 4.2)
    series = re.search(r"\b(\d+)S\b", battery.name)
    volts = re.search(r"(\d+(?:\.\d+)?)\s*V\b", battery.name)
    cells = int(series.group(1)) if series else round(float(volts.group(1)) / nominal) if volts else 4
    return round(cells * nominal, 1), round(cells * full, 1)


# ---------------------------------------------------------------- wiring
def wiring(project: RobotProject) -> dict:
    comps = project.components
    first = lambda kind: next((c for c in comps if c.kind == kind), None)  # noqa: E731
    qty = lambda kind: sum(c.quantity for c in comps if c.kind == kind)  # noqa: E731
    battery = first("battery")
    if battery:
        volts, full = pack_voltage(battery)
        source = battery.name
    else:
        volts = full = 12.0
        source = "12 V mains power supply"
    rows, extras, notes = [], [], []
    switched = 0.0    # motors and servos: cut by the e-stop
    always = 0.0      # computer, sensors, accessories

    motor = first("drive_motor")
    if motor:
        n = qty("drive_motor")
        rated_v = MOTOR_V.get(motor.catalog_id or "", 12.0)
        each = motor.specs.get("power_w", 30) / rated_v
        hub = rated_v >= 24
        drivers = 1 if n <= 2 else math.ceil(n / 2)
        driver = ("dual-channel BLDC hub-motor controller, 24-48 V, 15 A per channel (e.g. ZLAC8015D)" if hub
                  else "dual-channel brushed DC motor driver, 10 A per channel, 5-30 V (e.g. Cytron MDD10A)")
        extras.append(f"{drivers} × {driver}")
        supply = 2 * n * motor.specs.get("power_w", 30) / volts / drivers
        switched += n * motor.specs.get("power_w", 30) / volts
        note = ""
        if volts > rated_v * 1.15:
            note = f"Pack is {volts:g} V for {rated_v:g} V motors: cap PWM duty at {rated_v / volts:.0%} in firmware."
        elif volts < rated_v * 0.85:
            note = f"Motors are rated {rated_v:g} V; at {volts:g} V they reach about {volts / rated_v:.0%} of rated speed."
            if hub:
                notes.append("The hub-motor controller needs 24 V or more; use a 24 V (8S LiFePO4) pack.")
        rows.append(_power("E-stop contactor", f"Motor driver{'s' if drivers > 1 else ''} (VIN){f' ×{drivers}' if drivers > 1 else ''}",
                           volts, supply, note))
        rows.append(_power("Motor driver outputs (M1A/M1B, M2A/M2B)", f"{motor.name} ×{n}", min(volts, rated_v),
                           2 * each, "One pair per motor. If a wheel spins backwards, swap that motor's two wires.",
                           fused=False) | {"connector": "Driver screw terminals"})
        if hub:
            rows.append(_data("Hub motor hall sensors", "Controller hall ports", "5 V logic",
                              "5-pin hall lead supplied with the motor", "Match the colour order printed on the controller."))
        else:
            rows.append(_data("Motor encoders", "Microcontroller (e.g. Raspberry Pi Pico)", "3.3 V logic",
                              "4-wire encoder cable: A, B, 3.3 V, GND (JST-PH)",
                              "Use 3.3 V encoder power so the outputs are safe for the microcontroller pins."))
        rows.append(_data("Microcontroller", "Motor driver inputs", "3.3 V logic",
                          "PWM + DIR per channel and a shared GND (0.1\" jumper leads)" if not hub
                          else "RS485 or CAN pair from a USB adapter", "Driver logic GND must join the microcontroller GND."))
        rows.append(_data("Microcontroller", "Computer", "USB", "USB-A to micro-B/USB-C data cable",
                          "Runs the wheel speed loop and reports odometry."))
        extras.append("Microcontroller for wheel control and encoders (e.g. Raspberry Pi Pico or Teensy 4.0)")

    for kind, label, how in (("lift", "Lift actuator", "a spare motor-driver channel or a 10 A H-bridge"),
                             ("vacuum", "Vacuum blower", "its built-in ESC (PWM speed signal from the microcontroller)"),
                             ("side_brush", "Side brush motors", "a 2 A dual H-bridge rated above the pack's full voltage")):
        part = first(kind)
        if part:
            amps = part.specs.get("power_w", 10) * part.quantity / volts * (2 if kind == "lift" else 1.3)
            switched += part.specs.get("power_w", 10) * part.quantity / volts
            rows.append(_power("E-stop contactor", f"{label} via {how}", volts, amps))

    # One servo bus per brand and voltage: mixing them on a bus over-volts the lower-rated servos.
    buses: dict[tuple[bool, tuple[float, float]], list[Component]] = {}
    for c in comps:
        if c.kind == "arm_servo":
            key = ("dynamixel" in (c.catalog_id or ""), SERVO_V.get(c.catalog_id or "", (12, 14.8)))
            buses.setdefault(key, []).append(c)
    grip = first("gripper")
    if len(buses) > 1:
        notes.append("The arm mixes servo types, so it needs one bus per type. Joints on different buses "
                     "can't share a daisy chain.")
    for bus_index, ((dynamixel, (nominal, limit)), servos) in enumerate(buses.items()):
        watts = sum(c.specs.get("power_w", 12) * c.quantity for c in servos)
        if bus_index == len(buses) - 1 and grip:
            watts += grip.specs.get("power_w", 0)
        amps = watts / nominal * 1.5
        switched += watts / volts
        hub = "U2D2 Power Hub" if dynamixel else "servo bus power board"
        names = " + ".join(dict.fromkeys(c.name for c in servos))
        if full <= limit:
            rows.append(_power("E-stop contactor", f"{hub} ({names})", volts, amps,
                               f"The servos accept up to {limit:g} V, so the {full:g} V supply feeds them directly."))
        else:
            rows.append(_power("E-stop contactor", f"DC-DC buck converter → {nominal:g} V", volts, watts / volts * 1.5))
            rows.append(_power(f"{nominal:g} V buck output", f"{hub} ({names})", nominal, amps,
                               f"The supply reaches {full:g} V, above these servos' {limit:g} V limit."))
            extras.append(f"DC-DC buck converter, {nominal:g} V out, ≥{math.ceil(amps)} A")
        joints = sum(c.quantity for c in servos)
        rows.append(_power(hub, f"{names}: {joints} joints in a daisy chain", nominal, amps,
                           "Each servo has two bus ports: one in, one out. Leave slack at every joint.", fused=False) |
                    {"wire": "3-wire servo bus cable (power, GND, data)",
                     "connector": "JST EH 3-pin" if dynamixel else "Molex 5264 3-pin"})
        rows.append(_data("Computer", "U2D2 (USB to TTL)" if dynamixel else "Feetech URT-1 bus adapter", "USB",
                          "USB data cable", "Set each servo's ID (1 = base) before assembly."))
        extras.append("Robotis U2D2 + U2D2 Power Hub" if dynamixel else "Feetech URT-1 bus servo adapter")

    compute = first("compute")
    if compute:
        jetson = "jetson" in (compute.catalog_id or "")
        out_v, out_a = (19.0, compute.specs.get("power_w", 15) / 19 * 1.5) if jetson else (5.1, 5.0)
        converter = (f"DC-DC buck-boost converter, 19 V out, ≥{math.ceil(out_a)} A" if jetson
                     else "DC-DC buck converter, 5.1 V 5 A with USB-C PD output")
        extras.append(converter)
        draw = compute.specs.get("power_w", 10) / volts / 0.9
        always += draw
        rows.append(_power("Distribution block", converter.split(",")[0], volts, draw * 1.5))
        rows.append(_power(f"{out_v:g} V converter output", compute.name, out_v, out_a,
                           "5.5 × 2.5 mm barrel plug (centre positive)." if jetson
                           else "USB-C. The Pi 5 needs 5 A or it limits USB power.", fused=False)
                    | {"connector": "5.5 × 2.5 mm barrel" if jetson else "USB-C"})
        usb = [(first("camera"), "USB 3 Type-C cable, ≤1 m (USB 3 port)"), (first("lidar"), "USB cable via the lidar's adapter board"),
               (first("microphone"), "USB cable"), (first("display"), "HDMI cable + USB (touch and 5 V power)"),
               (first("proximity"), "I²C/GPIO leads, 3.3 V")]
        for part, cable in usb:
            if part:
                always += part.specs.get("power_w", 2) / volts / 0.9
                rows.append(_data(compute.name, part.name, "USB" if "USB" in cable else "3.3 V logic", cable,
                                  "Bus-powered from the computer." if "USB" in cable else ""))

    pan = first("pan_tilt")
    twelve = "direct" if full <= 16.8 else "a 12 V buck converter"
    accessories = [(pan, "a 6 V 3 A BEC" if pan and "servo" in (pan.catalog_id or "") else twelve),
                   (first("speaker"), "a 5 V buck and a 3 W stereo amplifier (e.g. PAM8403)"),
                   (first("lights"), f"a MOSFET switch from the microcontroller, {twelve}")]
    for part, how in accessories:
        if part:
            watts = part.specs.get("power_w", 5)
            always += watts / volts
            rows.append(_power("Distribution block", part.name + ("" if how == "direct" else f" via {how}"), volts,
                               max(0.5, watts / volts * 1.5)))

    total = switched + always
    motion = 2 * switched + 0.5      # motors and servos accelerating together
    main = motion + 1.25 * always + 0.5
    main_fuse = _fuse(main)
    rows.insert(0, _power(f"{source} (+)", "Main fuse → power switch → distribution block (+)", volts, main,
                          "Put the main fuse within 15 cm of the battery terminal." if battery else
                          "Use a supply rated at least this current."))
    rows.insert(1, _power(f"{source} (−)", "Distribution block (−)", volts, main,
                          "Same gauge as the positive lead. Every negative returns here.", fused=False)
                | {"wire": rows[0]["wire"].split(",")[0] + ", black", "connector": rows[0]["connector"]})
    if switched:
        rows.insert(2, _power("Distribution block (+)", "E-stop contactor (switched motor and servo power)", volts,
                              motion, "A latching mushroom e-stop opens the contactor coil and cuts all motion."))
        extras[:0] = [f"Latching mushroom e-stop switch + {_fuse(motion):g} A DC contactor/relay"]
    extras[:0] = [f"Main fuse holder + {main_fuse:g} A fuse" + (" (MIDI/ANL)" if main_fuse > 40 else " (ATO blade)"),
                  f"Power switch rated ≥{main_fuse:g} A DC", "Distribution block or bus bar (+ and −)"]
    gauges = sorted({int(m.group(1)) for r in rows if (m := re.match(r"(\d+) AWG", r["wire"]))})
    extras.append(f"Silicone wire, red and black: {', '.join(f'{g} AWG' for g in gauges)}")
    extras.append("Matching connectors (" + ", ".join(sorted({r['connector'] for r in rows if r['connector']})) + "), heat-shrink, ferrules")
    return {"source": source, "voltage_v": volts, "full_voltage_v": full, "total_a": round(total, 1),
            "estop": bool(switched), "rows": rows, "extras": extras, "notes": notes + [
                "Currents are estimates from rated power. Check them against each part's datasheet.",
                "Red is +, black is −. Crimp and heat-shrink every joint; never twist wires together.",
                "Run motor and power wires apart from USB and signal cables."]}


# ---------------------------------------------------------------- printable parts
def _volume(spec: PartSpec) -> float:
    """Approximate solid volume in mm³ (holes and vents ignored) for filament estimates."""
    L, W, t = spec.length_mm, spec.width_mm, spec.thickness_mm
    if spec.kind == "cover":
        f = 2 * spec.hole_inset_mm
        return L * W * spec.height_mm - (L - 2 * t) * (W - 2 * t) * (spec.height_mm - t) + ((L + 2 * f) * (W + 2 * f) - L * W) * t
    if spec.kind == "motor_bracket":
        return L * W * t + t * W * (spec.bracket_height_mm - t)
    return L * W * t


def _envelope(spec: PartSpec) -> list[float]:
    if spec.kind == "cover":
        f = 2 * spec.hole_inset_mm
        return [spec.length_mm + 2 * f, spec.width_mm + 2 * f, spec.height_mm]
    height = spec.bracket_height_mm if spec.kind == "motor_bracket" else spec.thickness_mm
    return [spec.length_mm, spec.width_mm, height]


ORIENTATION = {"cover": "Open side down, flange flat on the bed; enable supports for the roof.",
               "chassis_plate": "Flat on the bed, no supports.", "arm_link": "Flat on the bed, no supports.",
               "motor_bracket": "Base flat on the bed, no supports."}


def printables(project: RobotProject, assembly: Assembly) -> list[dict]:
    groups: dict[str, dict] = {}
    for node in assembly.nodes:
        if not node.spec:
            continue
        spec = PartSpec.model_validate(node.spec)
        key = spec.model_dump_json()
        if key in groups:
            groups[key]["quantity"] += 1
            continue
        groups[key] = {"name": spec.name, "kind": spec.kind, "component_id": node.component_id,
                       "quantity": 1, "spec": spec, "node": node}
    frame = next((n for n in assembly.nodes if n.role == "frame"), None)
    for c in project.components:
        if c.source != "generated" or any(g["component_id"] == c.id for g in groups.values()):
            continue
        if c.kind == "frame" and frame:
            spec = PartSpec(kind="chassis_plate", name=f"{c.name} deck", length_mm=round(frame.size[0] * 1000),
                            width_mm=round(frame.size[2] * 1000), thickness_mm=6, hole_diameter_mm=4.5,
                            hole_inset_mm=12, material="petg")
            groups[c.id] = {"name": spec.name, "kind": spec.kind, "component_id": c.id, "quantity": 1, "spec": spec}
        else:
            groups[c.id] = {"name": c.name, "kind": c.kind, "component_id": c.id, "quantity": c.quantity, "spec": None}

    items = []
    for index, g in enumerate(groups.values()):
        spec = g["spec"]
        if spec is None:
            items.append({"index": index, "name": g["name"], "kind": g["kind"], "component_id": g["component_id"],
                          "quantity": g["quantity"], "printable": False,
                          "note": "No print template for this part yet. Use a published STL or design it as a custom part."})
            continue
        if spec.material not in DENSITY_G_MM3:
            items.append({"index": index, "name": g["name"], "kind": g["kind"], "component_id": g["component_id"],
                          "quantity": g["quantity"], "printable": False,
                          "note": f"Specified in {spec.material}: machine it, or change the material to PETG to print it."})
            continue
        size = _envelope(spec)
        flat = sorted(size[:2])
        fits = flat[0] <= min(BED_MM[:2]) and flat[1] <= max(BED_MM[:2]) and size[2] <= BED_MM[2]
        grams = _volume(spec) * DENSITY_G_MM3[spec.material]
        items.append({
            "index": index, "name": g["name"], "kind": g["kind"], "component_id": g["component_id"],
            "quantity": g["quantity"], "printable": True, "material": spec.material.upper(),
            "size_mm": [round(v, 1) for v in size], "fits_bed": fits,
            "grams_each": round(grams), "hours_each": round(grams / GRAMS_PER_HOUR, 1),
            "settings": "0.2 mm layers, 4 walls, 25% gyroid infill, 240 °C nozzle / 80 °C bed" if spec.material == "petg"
                        else "0.2 mm layers, 4 walls, 25% gyroid infill, 210 °C nozzle / 60 °C bed",
            "orientation": ORIENTATION.get(spec.kind, "Largest flat face on the bed."),
            "note": "" if fits else (f"Larger than a {BED_MM[0]} × {BED_MM[1]} mm bed: print it on a large-format "
                                     "printer or split it into tiles joined with M3 screws and splice plates."),
            "spec": spec.model_dump(),
        })
    return items


def print_spec(project: RobotProject, index: int) -> PartSpec | None:
    """The validated template spec of one printable part, rebuilt from the project (never from the client)."""
    items = printables(project, build_assembly(project))
    if 0 <= index < len(items) and items[index].get("printable"):
        return PartSpec.model_validate(items[index]["spec"])
    return None


# ---------------------------------------------------------------- steps
def _step_of(node: Node) -> str:
    if node.role == "custom" and node.spec:
        return CUSTOM_STEP.get(node.spec.get("kind"), "modules")
    return ROLE_STEP.get(node.role, "modules")


def assembly_guide(project: RobotProject) -> dict:
    assembly = build_assembly(project)
    comps = project.components
    first = lambda kind: next((c for c in comps if c.kind == kind), None)  # noqa: E731
    names = lambda kinds: [c.name for c in comps if c.kind in kinds]  # noqa: E731
    by_step: dict[str, list[int]] = {}
    for index, node in enumerate(assembly.nodes):
        by_step.setdefault(_step_of(node), []).append(index)
    prints = printables(project, assembly)
    power = wiring(project)
    printed = [p for p in prints if p["printable"]]
    covers = [n for n in assembly.nodes if n.role == "cover"]
    frame, battery, compute = first("frame"), first("battery"), first("compute")
    motor, servos = first("drive_motor"), [c for c in comps if c.kind == "arm_servo"]
    dynamixel = any("dynamixel" in (c.catalog_id or "") for c in servos)
    inside = assembly.archetype in ("delivery_rover", "tracked_explorer", "warehouse_amr", "cleaning_robot",
                                    "telepresence", "security_patrol")

    steps = []

    by_step["print"] = [i for i, n in enumerate(assembly.nodes) if n.spec]  # shown alone, then again once fitted

    def step(key: str, title: str, items: list[str], parts: list[str] = ()) -> None:
        items = [i for i in items if i]
        if items:
            steps.append({"key": key, "title": title, "items": items, "nodes": by_step.get(key, []),
                          "components": sorted({assembly.nodes[i].component_id for i in by_step.get(key, [])
                                                if assembly.nodes[i].component_id} | set(parts))})

    if printed:
        total = sum(p["grams_each"] * p["quantity"] for p in printed)
        step("print", "Print the parts", [
            f"Print {sum(p['quantity'] for p in printed)} parts in PETG, about {total:,} g of filament in total. "
            "Download each STL from the print list below.",
            "Let PETG cool on the bed before removing it so the flanges stay flat.",
            "Press M3 heat-set inserts into printed parts where screws go into plastic."])
    step("frame", "Build the frame", [
        f"Lay out the {frame.name.lower()} on a flat table and assemble it square; measure both diagonals "
        "before tightening." if frame else "",
        "Screw the chassis plate onto the frame with M4 screws through its corner holes."
        if any(assembly.nodes[i].role == "custom" for i in by_step.get("frame", [])) else "",
        "Fit the ball casters front and back so the base sits level."
        if any(n.role == "caster" for n in assembly.nodes) else ""])
    step("drive", "Mount the drive", [
        f"Bolt the {sum(c.quantity for c in comps if c.kind == 'drive_motor')} drive motors ({motor.name}) into "
        "their mounts, shafts pointing out, and add medium threadlocker." if motor else "",
        "Use the printed motor brackets between each motor and the frame."
        if any(n.role == "custom" for n in assembly.nodes if _step_of(n) == "drive") else "",
        f"Fit the {first('wheel').name.lower()}s with the set screw on the flat of each shaft." if first("wheel") else "",
        "Fit the tracks and tension them until they deflect about 1 cm mid-span." if first("track") else ""])
    step("power", "Mount the battery", [
        f"Fix the battery ({battery.name}) {'inside the body' if inside else 'at the back of the deck'} with a bracket and a "
        "strap so it can't slide or tip." if battery else "",
        "Leave it disconnected until the power-on check at the end." if battery else ""])
    step("electronics", "Mount the electronics", [
        f"Mount the {compute.name} on M2.5 standoffs with space around its fan." if compute else "",
        "Mount the distribution block, main fuse, power switch and motor driver(s) close to the battery.",
        "Put the e-stop where it can be hit from outside the robot." if power["estop"] else ""],
        [c.id for c in comps if c.kind == "wiring"])
    others = names(("microphone", "pan_tilt", "display", "speaker", "lights", "proximity"))
    step("sensors", "Fit the sensors", [
        f"Mount the {first('camera').name} on its 1/4-20 thread, level and facing forward." if first("camera") else "",
        f"Mount the {first('lidar').name} level with a clear 360° view. Nothing on the robot should block its scan plane."
        if first("lidar") else "",
        f"Fit the {', '.join(others)}." if others else ""])
    module_ids = {assembly.nodes[i].component_id for i in by_step.get("modules", [])}
    step("modules", "Fit the job modules", [f"Fit the {c.name}." for c in comps if c.id in module_ids])
    if servos:
        joints = sum(c.quantity for c in servos)
        step("arm", "Build the arm", [
            f"Before assembly, give each of the {joints} servos its own ID (1 = base up to {joints} = wrist) with "
            f"{'Dynamixel Wizard 2.0' if dynamixel else 'Feetech FD software'}, and set every horn to its centre position.",
            "Assemble from the base up: base joint, shoulder, elbow, wrist, then the gripper.",
            "Daisy-chain the bus cables joint to joint with slack at each joint so nothing pulls when the arm moves."])
    step("wiring", "Wire it up", [
        "Follow the wiring table below, starting at the battery and working outwards.",
        "Fit the main fuse first, within 15 cm of the battery's + terminal." if battery else "",
        "Set each converter's output voltage with a multimeter before you connect its load.",
        "Tie cables down every 10 cm and leave a loop wherever a part moves."])
    if covers:
        step("covers", "Fit the covers", [
            "Route the cables out through the notch at the back of each cover.",
            f"Place the {' and the '.join(n.label.lower() for n in covers)} over their modules and fix each with "
            "4 × M3 × 10 screws through the flange.",
            "On a metal deck, drill 3.4 mm holes and use nuts; on a printed deck, use M3 heat-set inserts."])
    step("test", "Power on and test", [
        "With the battery disconnected, check there is no short between + and − at the distribution block.",
        "Lift the wheels off the ground, then connect the battery and switch on." if motor else "Switch on the supply.",
        "Hit the e-stop: every motor and servo must lose power while the computer stays on." if power["estop"] else "",
        "Drive each motor slowly and check it turns the right way." if motor else "",
        "Move each joint slowly with a low torque limit and check its direction and range." if servos else "",
        "Check the camera and sensors show up on the computer before the first drive."])
    return {"robot_type": assembly.robot_type, "steps": steps, "wiring": power, "prints": prints,
            "tools": TOOLS, "bed_mm": list(BED_MM),
            "notes": ["Assembly steps follow the layout; check fit and clearances as you build."]}
