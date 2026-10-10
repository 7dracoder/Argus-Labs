"""Central RobotProject data model shared by every agent and engine.

Every edit to a project creates a new revision (see store.py). Money values are
USD floats rounded to cents at reporting time; they are estimates, not quotes.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Category(str, Enum):
    mechanical = "mechanical"
    actuator = "actuator"
    sensor = "sensor"
    electronics = "electronics"
    power = "power"
    wiring = "wiring"
    manufacturing = "manufacturing"


class Requirements(BaseModel):
    description: str = ""
    tasks: list[str] = []
    environment: str = "indoor"
    payload_kg: float | None = None
    mobility: str | None = None  # wheeled, legged, fixed...
    runtime_hours: float | None = None
    budget_usd: float | None = Field(default=None, ge=0)
    contingency_pct: float = Field(default=10.0, ge=0, le=100)
    assumptions: list[str] = []  # unconfirmed assumptions awaiting user approval


class Component(BaseModel):
    """A real catalog part or an AI-generated parametric part."""

    id: str = Field(default_factory=lambda: uuid4().hex[:8])
    catalog_id: str | None = None
    name: str
    category: Category
    kind: str  # substitution group, e.g. "arm_servo", "battery"
    source: str = "catalog"  # "catalog" | "generated"
    quantity: int = Field(default=1, ge=1)
    unit_cost_usd: float = Field(ge=0)
    supplier: str | None = None
    lead_time_days: int | None = None
    specs: dict[str, float] = {}  # torque_nm, power_w, mass_kg, capacity_wh...


class ValidationRecord(BaseModel):
    check: str
    status: str  # "pass" | "fail" | "pending"
    detail: str = ""
    created_at: datetime = Field(default_factory=_now)


class ChatMessage(BaseModel):
    role: str  # "user" | "architect"
    content: str
    created_at: datetime = Field(default_factory=_now)


class RobotProject(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    name: str
    revision: int = 1
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    requirements: Requirements = Requirements()
    architecture: dict = {}  # robot type, dimensions, subsystems
    components: list[Component] = []
    assembly: dict = {}  # transforms, joints, interfaces
    electrical: dict = {}  # power, signals, wiring
    software: dict = {}  # controllers, drivers, behaviors
    simulation: dict = {}  # worlds, scenarios, outcomes
    manufacturing: dict = {}  # processes, materials, exports
    validation: list[ValidationRecord] = []
    conversation: list[ChatMessage] = []  # Architect interview history
