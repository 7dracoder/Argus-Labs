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
    "wiring": [],
}

CATALOG: dict[str, dict] = {
    # Arm actuators
    "dynamixel-xm430": dict(name="Dynamixel XM430-W350", category=Category.actuator, kind="arm_servo",
                            unit_cost_usd=290, supplier="Robotis", lead_time_days=7,
                            specs={"torque_nm": 4.1, "mass_kg": 0.082, "power_w": 12}),
    "feetech-sts3250": dict(name="Feetech STS3250", category=Category.actuator, kind="arm_servo",
                            unit_cost_usd=60, supplier="Feetech", lead_time_days=14,
                            specs={"torque_nm": 4.9, "mass_kg": 0.075, "power_w": 14}),
    "feetech-sts3215": dict(name="Feetech STS3215", category=Category.actuator, kind="arm_servo",
                            unit_cost_usd=20, supplier="Feetech", lead_time_days=14,
                            specs={"torque_nm": 2.9, "mass_kg": 0.055, "power_w": 10}),
    # Drive motors
    "maxon-dcx-gear": dict(name="Maxon DCX22 + GPX gearhead", category=Category.actuator, kind="drive_motor",
                           unit_cost_usd=320, supplier="Maxon", lead_time_days=21,
                           specs={"torque_nm": 2.0, "mass_kg": 0.25, "power_w": 40}),
    "pololu-37d-70to1": dict(name="Pololu 37D 70:1 gearmotor", category=Category.actuator, kind="drive_motor",
                             unit_cost_usd=50, supplier="Pololu", lead_time_days=5,
                             specs={"torque_nm": 2.4, "mass_kg": 0.21, "power_w": 30}),
    "jgb37-gearmotor": dict(name="JGB37 gearmotor", category=Category.actuator, kind="drive_motor",
                            unit_cost_usd=15, supplier="Generic", lead_time_days=20,
                            specs={"torque_nm": 1.2, "mass_kg": 0.18, "power_w": 20}),
    # Power
    "lifepo4-12v-20ah": dict(name="LiFePO4 12.8V 20Ah", category=Category.power, kind="battery",
                             unit_cost_usd=230, supplier="Generic", lead_time_days=10,
                             specs={"capacity_wh": 256, "mass_kg": 2.4}),
    "liion-4s-12ah": dict(name="Li-ion 4S 12Ah pack", category=Category.power, kind="battery",
                          unit_cost_usd=140, supplier="Generic", lead_time_days=10,
                          specs={"capacity_wh": 177, "mass_kg": 1.0}),
    # Compute
    "jetson-orin-nano": dict(name="NVIDIA Jetson Orin Nano", category=Category.electronics, kind="compute",
                             unit_cost_usd=250, supplier="NVIDIA", lead_time_days=7,
                             specs={"compute_score": 3, "power_w": 15}),
    "raspberry-pi-5": dict(name="Raspberry Pi 5 8GB", category=Category.electronics, kind="compute",
                           unit_cost_usd=80, supplier="Raspberry Pi", lead_time_days=5,
                           specs={"compute_score": 1, "power_w": 8}),
    # Sensors
    "realsense-d435": dict(name="Intel RealSense D435", category=Category.sensor, kind="camera",
                           unit_cost_usd=300, supplier="Intel", lead_time_days=7,
                           specs={"depth": 1, "power_w": 3.5}),
    "oak-d-lite": dict(name="Luxonis OAK-D Lite", category=Category.sensor, kind="camera",
                       unit_cost_usd=150, supplier="Luxonis", lead_time_days=10,
                       specs={"depth": 1, "power_w": 3}),
    "respeaker-array": dict(name="ReSpeaker mic array", category=Category.sensor, kind="microphone",
                            unit_cost_usd=70, supplier="Seeed", lead_time_days=7, specs={"power_w": 1}),
    # Mechanical / generated
    "alu-extrusion-frame": dict(name="Aluminum extrusion frame", category=Category.mechanical, kind="frame",
                                unit_cost_usd=120, supplier="Misumi", lead_time_days=7,
                                specs={"max_load_kg": 25, "mass_kg": 3.0}),
    "printed-petg-chassis": dict(name="Parametric PETG chassis (CadQuery)", category=Category.mechanical,
                                 kind="frame", source="generated", unit_cost_usd=60,
                                 specs={"max_load_kg": 12, "mass_kg": 1.8}),
    "printed-parallel-gripper": dict(name="Parametric parallel gripper (CadQuery)", category=Category.mechanical,
                                     kind="gripper", source="generated", unit_cost_usd=25,
                                     specs={"max_payload_kg": 2.5, "mass_kg": 0.2}),
    # Wiring
    "wiring-harness-kit": dict(name="Wiring harness + connectors", category=Category.wiring, kind="wiring",
                               unit_cost_usd=90, supplier="Generic", lead_time_days=5, specs={}),
}

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
    ("wiring-harness-kit", 1),
]


def make_component(catalog_id: str, quantity: int = 1) -> Component:
    if catalog_id not in CATALOG:
        raise KeyError(f"Unknown catalog id: {catalog_id}")
    return Component(catalog_id=catalog_id, quantity=quantity, **CATALOG[catalog_id])
