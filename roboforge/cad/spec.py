from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PartSpec(BaseModel):
    """A bounded geometry description, never executable model-generated Python."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, validate_default=True)
    name: str = Field(default="Robot part", min_length=1, max_length=120)
    kind: Literal["chassis_plate", "arm_link", "motor_bracket", "cover"]
    length_mm: float = Field(default=120, ge=10, le=1000)
    width_mm: float = Field(default=40, ge=10, le=1000)
    thickness_mm: float = Field(default=6, ge=1, le=50)
    hole_diameter_mm: float = Field(default=4, ge=1, le=50)
    hole_inset_mm: float = Field(default=10, ge=2, le=200)
    bracket_height_mm: float = Field(default=40, ge=10, le=300)
    height_mm: float = Field(default=60, ge=10, le=400)  # cover only: shell height
    vent_slots: int = Field(default=0, ge=0, le=12)       # cover only: slots in the top
    material: Literal["petg", "pla", "aluminum"] = "petg"

    @model_validator(mode="after")
    def check_interfaces(self):
        radius = self.hole_diameter_mm / 2
        if self.hole_inset_mm < radius + 1:
            raise ValueError("Mounting holes require at least 1 mm of edge material.")
        if self.kind == "cover":
            return self._check_cover()
        if self.length_mm - 2 * self.hole_inset_mm <= self.hole_diameter_mm + 1:
            raise ValueError("Length must leave separated mounting holes with 1 mm clearance.")
        if self.kind == "arm_link":
            if self.width_mm <= self.hole_diameter_mm + 2:
                raise ValueError("Arm link width must leave 1 mm of material on each side of the bore.")
        elif self.width_mm - 2 * self.hole_inset_mm <= self.hole_diameter_mm + 1:
            raise ValueError("Width must leave separated mounting holes with 1 mm clearance.")
        if self.kind == "motor_bracket":
            if self.bracket_height_mm <= self.thickness_mm:
                raise ValueError("Bracket height must exceed the base thickness.")
            if self.hole_inset_mm <= self.thickness_mm + radius + 1:
                raise ValueError("Bracket base holes must clear the upright wall by at least 1 mm.")
        return self

    def _check_cover(self):
        t = self.thickness_mm
        if min(self.length_mm, self.width_mm) - 2 * t < 20:
            raise ValueError("A cover needs at least 20 mm of space inside.")
        if min(12.0, (self.height_mm - t) / 2) <= t:
            raise ValueError("Cover height must leave room for the cable notch above the flange.")
        if 2 * self.hole_inset_mm < self.hole_diameter_mm + 2:
            raise ValueError("Cover flange must leave 1 mm of material around each screw hole.")
        if self.vent_slots and (self.vent_slots - 1) * VENT_PITCH_MM + VENT_WIDTH_MM > self.length_mm - 2 * t - 10:
            raise ValueError("Too many vent slots for this cover length.")
        return self


VENT_WIDTH_MM, VENT_PITCH_MM = 4.0, 8.0


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
