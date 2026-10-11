"""Multi-agent engineering system (skeleton).

Each agent reads and proposes changes to the same versioned RobotProject.
Agents propose; independent tools (VerificationAgent) verify.
Architect, Mechanical, and Finance agents are wired to their respective engines.
"""
from __future__ import annotations

from pydantic import BaseModel

from roboforge.catalog import CATALOG
from roboforge.finance import build_bom, check_budget, optimize_cost
from roboforge.llm import generate_structured
from roboforge.models import RobotProject


class Agent:
    name: str = "agent"
    output: str = ""

    def run(self, project: RobotProject, **kwargs) -> dict:
        raise NotImplementedError(f"{self.name} is not implemented yet")


class ArchitectTurn(BaseModel):
    """Structured output the Architect returns each conversation turn."""

    reply: str
    robot_category: str | None = None
    tasks: list[str] = []
    environment: str | None = None
    payload_kg: float | None = None
    mobility: str | None = None
    runtime_hours: float | None = None
    budget_usd: float | None = None
    assumptions: list[str] = []
    feasibility_concerns: list[str] = []
    next_question: str | None = None
    ready_for_design: bool = False


ARCHITECT_SYSTEM = """You are the RoboForge Robot Architect. Interview the user to build an
engineering specification for a robot. Each turn:
- Merge everything the user has said into the spec fields; never drop known facts.
- Ask exactly ONE next_question about the most important missing item
  (tasks, environment, payload, mobility, runtime, budget). Don't re-ask known facts.
- Be cost-aware: use the catalog price ranges to judge whether the budget is realistic.
  If the request is unrealistic (e.g. a $1,000 humanoid carrying 30 kg), say so in
  feasibility_concerns and suggest cheaper alternatives (wheels instead of legs, lower payload, higher budget).
- Prefer the simplest, cheapest architecture that meets the tasks.
- List guesses you made in assumptions so the user can confirm them.
- Set ready_for_design=true only when tasks, environment, payload, mobility and budget are known.
- reply is a short, plain-language message to the user ending with next_question if any."""


def _catalog_price_summary() -> str:
    ranges: dict[str, list[float]] = {}
    for item in CATALOG.values():
        ranges.setdefault(item["kind"], []).append(item["unit_cost_usd"])
    return "\n".join(f"- {k}: ${min(v):.0f}-${max(v):.0f} per unit" for k, v in sorted(ranges.items()))


class ArchitectAgent(Agent):
    name, output = "architect", "Robot specification and requirements"

    def run(self, project: RobotProject, message: str = "", **_) -> dict:
        transcript = "\n".join(f"{m.role}: {m.content}" for m in project.conversation)
        prompt = (
            f"Current spec:\n{project.requirements.model_dump_json(indent=1)}\n\n"
            f"Catalog price ranges:\n{_catalog_price_summary()}\n\n"
            f"Conversation so far:\n{transcript or '(none)'}\n\nuser: {message}"
        )
        turn = generate_structured(ARCHITECT_SYSTEM, prompt, ArchitectTurn)

        old = project.requirements
        updated = old.model_copy(update={
            "description": old.description or message,
            "tasks": turn.tasks or old.tasks,
            "environment": turn.environment or old.environment,
            "payload_kg": turn.payload_kg if turn.payload_kg is not None else old.payload_kg,
            "mobility": turn.mobility or old.mobility,
            "runtime_hours": turn.runtime_hours if turn.runtime_hours is not None else old.runtime_hours,
            "budget_usd": turn.budget_usd if turn.budget_usd is not None and turn.budget_usd >= 0
            else old.budget_usd,
            "assumptions": turn.assumptions or old.assumptions,
        })

        # Independent, deterministic budget check: don't trust the LLM's arithmetic.
        concerns = list(turn.feasibility_concerns)
        if project.components and updated.budget_usd is not None:
            report = check_budget(build_bom(project.components), updated.budget_usd, updated.contingency_pct)
            if report.status == "over_budget":
                concerns.append(f"Current parts list projects ${report.projected_total_usd:,.2f} "
                                f"(incl. contingency), ${-report.remaining_usd:,.2f} over budget.")

        return {"turn": turn, "requirements": updated, "feasibility_concerns": concerns,
                "robot_category": turn.robot_category}


class MechanicalAgent(Agent):
    name, output = "mechanical", "Parametric robot parts, verified STEP/STL/GLB exports"

    def run(self, project: RobotProject, request, **_) -> dict:
        from roboforge.cad.engine import build
        from roboforge.cad.spec import PartProposal

        base = None
        if request.base_design_id:
            base = project.manufacturing.get("cad_parts", {}).get(request.base_design_id)
            if base is None:
                raise ValueError("Base design is not attached to this project revision.")
        assumptions = []
        explanation = "Built from explicitly supplied dimensions."
        spec = request.spec
        if request.prompt:
            from roboforge.cad.profiles import prompt_catalog_text, suggest_signature_part
            suggested = suggest_signature_part(project.requirements)
            proposal = generate_structured(
                """Select one supported robot part and propose dimensions in millimeters.
Choose the template that best matches THIS robot's mobility, tasks and payload — do not
default every request to arm_link. Supported templates:
""" + prompt_catalog_text() + """
Wheel hub uses length_mm as outer diameter and width_mm as bolt-circle diameter.
Sensor/motor brackets use bracket_height_mm for the upright.
Use bounded PartSpec fields only. Preserve base parameters for edits unless requested.
A suggested signature part for this project is provided as a starting point; follow the
user request when it clearly asks for a different supported kind.
List unconfirmed dimensions, motor compatibility and material choices as assumptions.
Do not claim a whole robot, structural safety or fit has been demonstrated.
If the user asks for unsupported geometry, explain this limitation and list any proposed
simplification in assumptions. Do not invent a motor's mounting dimensions.""",
                f"Requirements: {project.requirements.model_dump_json()}\n"
                f"Suggested signature part: {suggested.model_dump_json()}\n"
                f"Base part: {base['spec'] if base else 'none'}\nRequest: {request.prompt}",
                PartProposal,
            )
            spec, assumptions, explanation = proposal.spec, proposal.assumptions, proposal.explanation
        result = build(spec)
        return {**result, "assumptions": assumptions, "explanation": explanation,
                "base_design_id": request.base_design_id}


class ElectricalAgent(Agent):
    name, output = "electrical", "Schematics, power budget, electrical BOM"


class SoftwareAgent(Agent):
    name, output = "software", "URDF/MJCF and ROS 2 project"


class VerificationAgent(Agent):
    name, output = "verification", "Simulation results and validation report"


class ManufacturingAgent(Agent):
    name, output = "manufacturing", "STEP/STL exports and assembly kit"


class FinanceAgent(Agent):
    name, output = "finance", "Cost report and optimization proposals"

    def run(self, project: RobotProject, target_savings_usd: float | None = None, **_) -> dict:
        bom = build_bom(project.components)
        budget = check_budget(bom, project.requirements.budget_usd, project.requirements.contingency_pct)
        if target_savings_usd is None and budget.status == "over_budget":
            target_savings_usd = -budget.remaining_usd
        _, proposal = optimize_cost(project.components, target_savings_usd)
        return {"bom": bom, "budget": budget, "proposal": proposal}


AGENTS: dict[str, Agent] = {a.name: a for a in (
    ArchitectAgent(), MechanicalAgent(), ElectricalAgent(), SoftwareAgent(),
    VerificationAgent(), FinanceAgent(), ManufacturingAgent(),
)}
