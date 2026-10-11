"""Curated component catalog.

Prices are illustrative placeholders for development, not supplier quotes.

`kind` groups interchangeable parts. `CRITICAL_SPECS` lists the higher-is-better
specs a substitute must meet or exceed so cost cuts don't degrade capability.
"""
from __future__ import annotations

from roboforge.models import Category, Component

CRITICAL_SPECS: dict[str, list[str]] = {
    "arm_servo": ["torque_nm"],
    "drive_motor": ["torque_nm"],
    "battery": ["capacity_wh"],
    "compute": ["compute_score"],
    "camera": ["depth"],
    "frame": ["max_load_kg"],
    "gripper": ["max_payload_kg"],
    "microphone": [],
    "lidar": ["range_m"],
    "wheel": ["max_load_kg"],
    "track": ["max_load_kg"],
    "lift": ["max_load_kg"],
    "cargo_bin": ["volume_l"],
    "vacuum": ["suction_pa"],
    "display": [],
    "pan_tilt": [],
    "wiring": [],
}

CATALOG: dict[str, dict] = {
    # Arm actuators
    "dynamixel-xm430": dict(name="Dynamixel XM430-W350", category=Category.actuator, kind="arm_servo",
                            unit_cost_usd=290, supplier="Robotis", lead_time_days=7,
                            specs={"torque_nm": 4.1, "mass_kg": 0.082, "power_w": 12, "quality": 4}),
    "feetech-sts3250": dict(name="Feetech STS3250", category=Category.actuator, kind="arm_servo",
                            unit_cost_usd=60, supplier="Feetech", lead_time_days=14,
                            specs={"torque_nm": 4.9, "mass_kg": 0.075, "power_w": 14, "quality": 3}),
    "feetech-sts3215": dict(name="Feetech STS3215", category=Category.actuator, kind="arm_servo",
                            unit_cost_usd=20, supplier="Feetech", lead_time_days=14,
                            specs={"torque_nm": 2.9, "mass_kg": 0.055, "power_w": 10, "quality": 2}),
    # Drive motors
    "maxon-dcx-gear": dict(name="Maxon DCX22 + GPX gearhead", category=Category.actuator, kind="drive_motor",
                           unit_cost_usd=320, supplier="Maxon", lead_time_days=21,
                           specs={"torque_nm": 2.0, "mass_kg": 0.25, "power_w": 40, "quality": 5}),
    "pololu-37d-70to1": dict(name="Pololu 37D 70:1 gearmotor", category=Category.actuator, kind="drive_motor",
                             unit_cost_usd=50, supplier="Pololu", lead_time_days=5,
                             specs={"torque_nm": 2.4, "mass_kg": 0.21, "power_w": 30, "quality": 3}),
    "jgb37-gearmotor": dict(name="JGB37 gearmotor", category=Category.actuator, kind="drive_motor",
                            unit_cost_usd=15, supplier="Generic", lead_time_days=20,
                            specs={"torque_nm": 1.2, "mass_kg": 0.18, "power_w": 20, "quality": 1}),
    "gobilda-5203-50to1": dict(name="goBILDA 5203 50.9:1 planetary gearmotor", category=Category.actuator,
                               kind="drive_motor", unit_cost_usd=65, supplier="goBILDA", lead_time_days=6,
                               specs={"torque_nm": 5.4, "mass_kg": 0.43, "power_w": 60, "quality": 4}),
    # Power
    "lifepo4-12v-20ah": dict(name="LiFePO4 12.8V 20Ah", category=Category.power, kind="battery",
                             unit_cost_usd=230, supplier="Generic", lead_time_days=10,
                             specs={"capacity_wh": 256, "mass_kg": 2.4, "quality": 4}),
    "liion-4s-12ah": dict(name="Li-ion 4S 12Ah pack", category=Category.power, kind="battery",
                          unit_cost_usd=140, supplier="Generic", lead_time_days=10,
                          specs={"capacity_wh": 177, "mass_kg": 1.0, "quality": 3}),
    # Compute
    "jetson-orin-nano": dict(name="NVIDIA Jetson Orin Nano", category=Category.electronics, kind="compute",
                             unit_cost_usd=250, supplier="NVIDIA", lead_time_days=7,
                             specs={"compute_score": 3, "power_w": 15, "quality": 4}),
    "raspberry-pi-5": dict(name="Raspberry Pi 5 8GB", category=Category.electronics, kind="compute",
                           unit_cost_usd=80, supplier="Raspberry Pi", lead_time_days=5,
                           specs={"compute_score": 1, "power_w": 8, "quality": 2}),
    # Sensors
    "realsense-d435": dict(name="Intel RealSense D435", category=Category.sensor, kind="camera",
                           unit_cost_usd=300, supplier="Intel", lead_time_days=7,
                           specs={"depth": 1, "power_w": 3.5, "quality": 4}),
    "oak-d-lite": dict(name="Luxonis OAK-D Lite", category=Category.sensor, kind="camera",
                       unit_cost_usd=150, supplier="Luxonis", lead_time_days=10,
                       specs={"depth": 1, "power_w": 3, "quality": 3}),
    "respeaker-array": dict(name="ReSpeaker mic array", category=Category.sensor, kind="microphone",
                            unit_cost_usd=70, supplier="Seeed", lead_time_days=7, specs={"power_w": 1, "quality": 3}),
    # Mechanical / generated
    "alu-extrusion-frame": dict(name="Aluminum extrusion frame", category=Category.mechanical, kind="frame",
                                unit_cost_usd=120, supplier="Misumi", lead_time_days=7,
                                specs={"max_load_kg": 25, "mass_kg": 3.0, "quality": 4}),
    "printed-petg-chassis": dict(name="Parametric PETG chassis (CadQuery)", category=Category.mechanical,
                                 kind="frame", source="generated", unit_cost_usd=60,
                                 specs={"max_load_kg": 12, "mass_kg": 1.8, "quality": 2}),
    "printed-parallel-gripper": dict(name="Parametric parallel gripper (CadQuery)", category=Category.mechanical,
                                     kind="gripper", source="generated", unit_cost_usd=25,
                                     specs={"max_payload_kg": 2.5, "mass_kg": 0.2, "quality": 2}),
    # Higher-end options the budget optimizer can upgrade into
    "dynamixel-xm540": dict(name="Dynamixel XM540-W270", category=Category.actuator, kind="arm_servo",
                            unit_cost_usd=495, supplier="Robotis", lead_time_days=7,
                            specs={"torque_nm": 10.6, "mass_kg": 0.165, "power_w": 20, "quality": 5}),
    "jetson-orin-nx": dict(name="NVIDIA Jetson Orin NX 16GB", category=Category.electronics, kind="compute",
                           unit_cost_usd=640, supplier="NVIDIA", lead_time_days=10,
                           specs={"compute_score": 5, "power_w": 25, "quality": 5}),
    "zed-2i": dict(name="Stereolabs ZED 2i", category=Category.sensor, kind="camera",
                   unit_cost_usd=500, supplier="Stereolabs", lead_time_days=10,
                   specs={"depth": 1, "power_w": 2, "quality": 5}),
    "lifepo4-12v-40ah": dict(name="LiFePO4 12.8V 40Ah", category=Category.power, kind="battery",
                             unit_cost_usd=410, supplier="Generic", lead_time_days=10,
                             specs={"capacity_wh": 512, "mass_kg": 4.3, "quality": 5}),
    "rplidar-a1": dict(name="Slamtec RPLIDAR A1", category=Category.sensor, kind="lidar",
                       unit_cost_usd=99, supplier="Slamtec", lead_time_days=7,
                       specs={"range_m": 12, "power_w": 2.5, "quality": 3}),
    "rplidar-s2": dict(name="Slamtec RPLIDAR S2", category=Category.sensor, kind="lidar",
                       unit_cost_usd=399, supplier="Slamtec", lead_time_days=10,
                       specs={"range_m": 30, "power_w": 4, "quality": 5}),
    "alu-servo-gripper": dict(name="Aluminium servo gripper", category=Category.mechanical, kind="gripper",
                              unit_cost_usd=95, supplier="Generic", lead_time_days=10,
                              specs={"max_payload_kg": 3.5, "mass_kg": 0.25, "power_w": 6, "quality": 4}),
    # Wheels (per wheel) - chosen per body plan and terrain
    "wheel-65-rubber": dict(name="65 mm rubber wheel", category=Category.mechanical, kind="wheel",
                            unit_cost_usd=6, supplier="Pololu", lead_time_days=5,
                            specs={"diameter_mm": 65, "max_load_kg": 4, "quality": 2, "mass_kg": 0.04}),
    "wheel-100-pu": dict(name="100 mm polyurethane wheel", category=Category.mechanical, kind="wheel",
                         unit_cost_usd=14, supplier="ServoCity", lead_time_days=5,
                         specs={"diameter_mm": 100, "max_load_kg": 15, "quality": 3, "mass_kg": 0.12}),
    "wheel-150-pneumatic": dict(name="150 mm pneumatic wheel", category=Category.mechanical, kind="wheel",
                                unit_cost_usd=28, supplier="ServoCity", lead_time_days=7,
                                specs={"diameter_mm": 150, "max_load_kg": 30, "quality": 4, "mass_kg": 0.35}),
    "wheel-100-mecanum": dict(name="100 mm mecanum wheel", category=Category.mechanical, kind="wheel",
                              unit_cost_usd=38, supplier="Nexus", lead_time_days=10,
                              specs={"diameter_mm": 100, "max_load_kg": 20, "quality": 5, "mass_kg": 0.30,
                                     "omni": 1}),
    "track-kit-rubber": dict(name="Rubber track kit (pair)", category=Category.mechanical, kind="track",
                             unit_cost_usd=160, supplier="Generic", lead_time_days=14,
                             specs={"max_load_kg": 20, "quality": 3, "mass_kg": 1.6}),
    "track-kit-alu": dict(name="Aluminium-link track kit (pair)", category=Category.mechanical, kind="track",
                          unit_cost_usd=420, supplier="Generic", lead_time_days=21,
                          specs={"max_load_kg": 45, "quality": 5, "mass_kg": 2.6}),
    "wheel-150-pu-heavy": dict(name="150 mm heavy-duty PU drive wheel", category=Category.mechanical, kind="wheel",
                               unit_cost_usd=35, supplier="Colson", lead_time_days=10,
                               specs={"diameter_mm": 150, "max_load_kg": 80, "quality": 4, "mass_kg": 0.6}),
    # Heavy-duty drive train and power for AMRs
    "steel-amr-chassis": dict(name="Welded steel AMR chassis", category=Category.mechanical, kind="frame",
                              unit_cost_usd=380, supplier="Generic", lead_time_days=21,
                              specs={"max_load_kg": 160, "mass_kg": 14, "quality": 5}),
    # Body-plan specific frames (see BODY_FIT)
    "rover-alu-chassis": dict(name="Sealed aluminium rover chassis", category=Category.mechanical, kind="frame",
                              unit_cost_usd=210, supplier="Generic", lead_time_days=14,
                              specs={"max_load_kg": 45, "mass_kg": 6.0, "quality": 4}),
    "rugged-tracked-hull": dict(name="Rugged aluminium tracked hull", category=Category.mechanical, kind="frame",
                                unit_cost_usd=230, supplier="Generic", lead_time_days=14,
                                specs={"max_load_kg": 40, "mass_kg": 5.5, "quality": 4}),
    "abs-round-shell": dict(name="Moulded ABS round body shell", category=Category.mechanical, kind="frame",
                            unit_cost_usd=75, supplier="Generic", lead_time_days=10,
                            specs={"max_load_kg": 15, "mass_kg": 1.4, "quality": 3}),
    "bench-base-plate": dict(name="Aluminium bench base plate", category=Category.mechanical, kind="frame",
                             unit_cost_usd=45, supplier="Misumi", lead_time_days=7,
                             specs={"max_load_kg": 20, "mass_kg": 2.2, "quality": 3}),
    "hub-motor-250w": dict(name="250 W geared hub motor", category=Category.actuator, kind="drive_motor",
                           unit_cost_usd=170, supplier="Generic", lead_time_days=14,
                           specs={"torque_nm": 18, "mass_kg": 2.1, "power_w": 250, "quality": 4}),
    "lifepo4-24v-50ah": dict(name="LiFePO4 25.6V 50Ah", category=Category.power, kind="battery",
                             unit_cost_usd=640, supplier="Generic", lead_time_days=14,
                             specs={"capacity_wh": 1280, "mass_kg": 11, "quality": 5}),
    # Bodies and payload modules
    "printed-cargo-bin": dict(name="Printed cargo bin with lid", category=Category.mechanical, kind="cargo_bin",
                              source="generated", unit_cost_usd=35,
                              specs={"volume_l": 18, "quality": 2, "mass_kg": 0.9}),
    "printed-cover": dict(name="Printed PETG protective cover", category=Category.mechanical, kind="cover",
                          source="generated", unit_cost_usd=8, specs={"quality": 3, "mass_kg": 0.15}),
    "alu-cargo-bin": dict(name="Lockable aluminium cargo bin", category=Category.mechanical, kind="cargo_bin",
                          unit_cost_usd=140, supplier="Generic", lead_time_days=10,
                          specs={"volume_l": 30, "quality": 4, "mass_kg": 2.2}),
    "lift-actuator-50kg": dict(name="Linear lift actuator 50 kg", category=Category.actuator, kind="lift",
                               unit_cost_usd=95, supplier="Progressive Automations", lead_time_days=10,
                               specs={"max_load_kg": 50, "power_w": 40, "quality": 3, "mass_kg": 1.4}),
    "lift-actuator-150kg": dict(name="Heavy-duty lift actuator 150 kg", category=Category.actuator, kind="lift",
                                unit_cost_usd=260, supplier="Progressive Automations", lead_time_days=14,
                                specs={"max_load_kg": 150, "power_w": 70, "quality": 5, "mass_kg": 2.8}),
    "pan-tilt-servo": dict(name="Servo pan-tilt head", category=Category.actuator, kind="pan_tilt",
                           unit_cost_usd=45, supplier="Generic", lead_time_days=7,
                           specs={"power_w": 6, "quality": 2, "mass_kg": 0.25}),
    "pan-tilt-gimbal": dict(name="Brushless pan-tilt gimbal", category=Category.actuator, kind="pan_tilt",
                            unit_cost_usd=240, supplier="Generic", lead_time_days=10,
                            specs={"power_w": 10, "quality": 5, "mass_kg": 0.45}),
    "display-7in": dict(name="7-inch touch display", category=Category.electronics, kind="display",
                        unit_cost_usd=60, supplier="Waveshare", lead_time_days=7,
                        specs={"diagonal_in": 7, "power_w": 4, "quality": 3, "mass_kg": 0.3}),
    "display-10in": dict(name="10.1-inch IPS touch display", category=Category.electronics, kind="display",
                         unit_cost_usd=130, supplier="Waveshare", lead_time_days=7,
                         specs={"diagonal_in": 10.1, "power_w": 7, "quality": 5, "mass_kg": 0.55}),
    "speaker-3w": dict(name="3 W speaker pair", category=Category.electronics, kind="speaker",
                       unit_cost_usd=12, supplier="Adafruit", lead_time_days=5,
                       specs={"power_w": 3, "quality": 3, "mass_kg": 0.1}),
    "vacuum-blower": dict(name="Brushless vacuum blower", category=Category.actuator, kind="vacuum",
                          unit_cost_usd=48, supplier="Generic", lead_time_days=10,
                          specs={"suction_pa": 2500, "power_w": 30, "quality": 3, "mass_kg": 0.35}),
    "vacuum-blower-pro": dict(name="High-suction vacuum module", category=Category.actuator, kind="vacuum",
                              unit_cost_usd=120, supplier="Generic", lead_time_days=14,
                              specs={"suction_pa": 5000, "power_w": 45, "quality": 5, "mass_kg": 0.5}),
    "side-brush-kit": dict(name="Side brush motor kit (pair)", category=Category.actuator, kind="side_brush",
                           unit_cost_usd=18, supplier="Generic", lead_time_days=10,
                           specs={"power_w": 4, "quality": 3, "mass_kg": 0.15}),
    "bumper-tof-array": dict(name="Bumper + ToF obstacle sensors", category=Category.sensor, kind="proximity",
                             unit_cost_usd=35, supplier="Generic", lead_time_days=7,
                             specs={"power_w": 1, "quality": 3, "mass_kg": 0.1}),
    "led-light-bar": dict(name="LED light bar + indicators", category=Category.electronics, kind="lights",
                          unit_cost_usd=22, supplier="Generic", lead_time_days=5,
                          specs={"power_w": 6, "quality": 3, "mass_kg": 0.1}),
    # Wiring
    "wiring-harness-kit": dict(name="Wiring harness + connectors", category=Category.wiring, kind="wiring",
                               unit_cost_usd=90, supplier="Generic", lead_time_days=5, specs={}),
}

# Body plans (archetype keys) a part physically suits; unlisted parts suit any. These
# parts are only picked or substituted within a matching body plan, so a rover never
# gets a desk-arm base.
BODY_FIT: dict[str, frozenset[str]] = {
    "alu-extrusion-frame": frozenset({"mobile_manipulator", "mobile_robot", "stationary_arm"}),
    "printed-petg-chassis": frozenset({"mobile_robot", "mobile_manipulator", "cleaning_robot"}),
    "steel-amr-chassis": frozenset({"warehouse_amr"}),
    "rover-alu-chassis": frozenset({"delivery_rover"}),
    "rugged-tracked-hull": frozenset({"tracked_explorer"}),
    "abs-round-shell": frozenset({"cleaning_robot", "telepresence", "security_patrol"}),
    "bench-base-plate": frozenset({"stationary_arm"}),
    "hub-motor-250w": frozenset({"warehouse_amr", "delivery_rover"}),  # wheel hub motor, no tracks
    "gobilda-5203-50to1": frozenset({"tracked_explorer", "delivery_rover", "mobile_manipulator", "mobile_robot",
                                     "telepresence", "security_patrol"}),  # too big for a slim vacuum
}


def same_body_fit(a: str | None, b: str | None) -> bool:
    """True if two catalog parts can replace each other on the same body plan."""
    fa, fb = BODY_FIT.get(a or ""), BODY_FIT.get(b or "")
    return fa is None or fb is None or bool(fa & fb)

# Prototype: wheeled household robot with one arm (intentionally over a $2,500 budget).
DEMO_BUILD: list[tuple[str, int]] = [
    ("alu-extrusion-frame", 1),
    ("maxon-dcx-gear", 2),
    ("dynamixel-xm430", 5),
    ("printed-parallel-gripper", 1),
    ("lifepo4-12v-20ah", 1),
    ("jetson-orin-nano", 1),
    ("realsense-d435", 1),
    ("respeaker-array", 1),
    ("printed-cover", 2),
    ("wiring-harness-kit", 1),
]


def make_component(catalog_id: str, quantity: int = 1) -> Component:
    if catalog_id not in CATALOG:
        raise KeyError(f"Unknown catalog id: {catalog_id}")
    return Component(catalog_id=catalog_id, quantity=quantity, **CATALOG[catalog_id])
