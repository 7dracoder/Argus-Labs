from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PartKind = Literal[
    "chassis_plate",
    "arm_link",
    "motor_bracket",
    "wheel_hub",
    "gripper_jaw",
    "sensor_mount",
]

PART_KINDS: tuple[PartKind, ...] = (
    "chassis_plate",
    "arm_link",
    "motor_bracket",
    "wheel_hub",
    "gripper_jaw",
    "sensor_mount",
)


class PartSpec(BaseModel):
    """A bounded geometry description, never executable model-generated Python."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, validate_default=True)
    name: str = Field(default="Robot part", min_length=1, max_length=120)
    kind: PartKind
    length_mm: float = Field(default=120, ge=10, le=1000)
    width_mm: float = Field(default=40, ge=10, le=1000)
    thickness_mm: float = Field(default=6, ge=1, le=50)
    hole_diameter_mm: float = Field(default=4, ge=1, le=50)
    hole_inset_mm: float = Field(default=10, ge=2, le=200)
    bracket_height_mm: float = Field(default=40, ge=10, le=300)
    material: Literal["petg", "pla", "aluminum"] = "petg"

    @model_validator(mode="after")
    def check_interfaces(self):
        radius = self.hole_diameter_mm / 2
        if self.kind == "wheel_hub":
            if self.width_mm >= self.length_mm - 2 * self.hole_diameter_mm:
                raise ValueError("Wheel hub bolt circle must sit inside the flange with clearance.")
            if self.hole_diameter_mm >= self.width_mm * 0.45:
                raise ValueError("Wheel hub axle bore must leave material inside the bolt circle.")
            if self.thickness_mm < 3:
                raise ValueError("Wheel hub thickness must be at least 3 mm.")
            return self

        if self.hole_inset_mm < radius + 1:
            raise ValueError("Mounting holes require at least 1 mm of edge material.")
        if self.length_mm - 2 * self.hole_inset_mm <= self.hole_diameter_mm + 1:
            raise ValueError("Length must leave separated mounting holes with 1 mm clearance.")

        if self.kind in {"arm_link", "gripper_jaw"}:
            if self.width_mm <= self.hole_diameter_mm + 2:
                raise ValueError("Part width must leave 1 mm of material on each side of the bore.")
            if self.kind == "arm_link" and self.length_mm <= self.width_mm + 20:
                raise ValueError("Arm link length must exceed width by at least 20 mm for end radii.")
            if self.kind == "gripper_jaw":
                if self.length_mm < 40:
                    raise ValueError("Gripper jaw length must be at least 40 mm.")
                span = max(self.hole_diameter_mm + 6, 12)
                if self.hole_inset_mm + span + self.hole_diameter_mm / 2 + 1 >= self.length_mm / 2:
                    raise ValueError("Gripper jaw mount bores must remain on the base half of the finger.")
            return self

        if self.kind == "sensor_mount":
            if self.width_mm - 2 * self.hole_inset_mm <= self.hole_diameter_mm + 1:
                raise ValueError("Width must leave separated mounting holes with 1 mm clearance.")
            if self.bracket_height_mm <= self.thickness_mm + 12:
                raise ValueError("Sensor mount upright must clear the base and leave room for a camera slot.")
            if self.hole_inset_mm <= self.thickness_mm + radius + 1:
                raise ValueError("Sensor mount base holes must clear the upright wall by at least 1 mm.")
            return self

        if self.width_mm - 2 * self.hole_inset_mm <= self.hole_diameter_mm + 1:
            raise ValueError("Width must leave separated mounting holes with 1 mm clearance.")
        if self.kind == "motor_bracket":
            if self.bracket_height_mm <= self.thickness_mm:
                raise ValueError("Bracket height must exceed the base thickness.")
            if self.hole_inset_mm <= self.thickness_mm + radius + 1:
                raise ValueError("Bracket base holes must clear the upright wall by at least 1 mm.")
        if self.kind == "chassis_plate" and min(self.length_mm, self.width_mm) < 40:
            raise ValueError("Chassis plate needs at least 40 mm on the short side for a cable pass-through.")
        return self


class PartProposal(BaseModel):
    spec: PartSpec
    assumptions: list[str] = Field(default_factory=list)
    explanation: str


class MechanicalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    prompt: str | None = Field(default=None, min_length=1, max_length=4000)
    spec: PartSpec | None = None
    base_design_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    estimated_unit_cost_usd: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def choose_input(self):
        if (self.prompt is None) == (self.spec is None):
            raise ValueError("Provide exactly one of prompt or spec.")
        return self
