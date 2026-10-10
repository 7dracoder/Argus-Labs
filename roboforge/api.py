"""HTTP API: projects, catalog and finance endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from roboforge.agents import AGENTS
from roboforge.catalog import CATALOG, DEMO_BUILD, make_component
from roboforge.finance import TCOInput, build_bom, check_budget, estimate_tco, optimize_cost
from roboforge.llm import LLMUnavailable
from roboforge.models import ChatMessage, Component, Requirements, RobotProject, ValidationRecord
from roboforge.store import store

router = APIRouter()


def _get(project_id: str, revision: int | None = None) -> RobotProject:
    project = store.get(project_id, revision)
    if project is None:
        raise HTTPException(404, "Project or revision not found")
    return project


# ---- Projects ---------------------------------------------------------------

class CreateProject(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    requirements: Requirements = Requirements()


class AddComponent(BaseModel):
    catalog_id: str | None = None
    quantity: int = Field(default=1, ge=1, le=1000)
    custom: Component | None = None  # for generated/non-catalog parts


@router.post("/projects", response_model=RobotProject, status_code=201)
def create_project(body: CreateProject):
    return store.create(RobotProject(name=body.name, requirements=body.requirements))


@router.post("/projects/demo", response_model=RobotProject, status_code=201)
def create_demo_project():
    """Wheeled household robot with one arm, $2,500 budget (starts over budget)."""
    return store.create(RobotProject(
        name="Household mobile manipulator",
        requirements=Requirements(
            description="Pick up clothes, carry small objects, respond to voice, one-floor apartment.",
            tasks=["pick up items", "carry objects", "voice commands"],
            payload_kg=2, mobility="wheeled", runtime_hours=2, budget_usd=2500,
            assumptions=["Single arm is sufficient", "No stairs"],
        ),
        architecture={"type": "mobile_manipulator", "subsystems": ["base", "arm", "gripper", "perception"]},
        components=[make_component(cid, qty) for cid, qty in DEMO_BUILD],
    ))


@router.get("/projects", response_model=list[RobotProject])
def list_projects():
    return store.list()


@router.get("/projects/{project_id}", response_model=RobotProject)
def get_project(project_id: str, revision: int | None = None):
    return _get(project_id, revision)


@router.patch("/projects/{project_id}/requirements", response_model=RobotProject)
def update_requirements(project_id: str, body: Requirements):
    project = _get(project_id)
    project.requirements = body
    return store.save_revision(project)


@router.post("/projects/{project_id}/components", response_model=RobotProject)
def add_component(project_id: str, body: AddComponent):
    project = _get(project_id)
    if body.custom:
        component = body.custom
    elif body.catalog_id:
        try:
            component = make_component(body.catalog_id, body.quantity)
        except KeyError as e:
            raise HTTPException(404, str(e))
    else:
        raise HTTPException(422, "Provide catalog_id or custom")
    project.components.append(component)
    return store.save_revision(project)


@router.delete("/projects/{project_id}/components/{component_id}", response_model=RobotProject)
def remove_component(project_id: str, component_id: str):
    project = _get(project_id)
    remaining = [c for c in project.components if c.id != component_id]
    if len(remaining) == len(project.components):
        raise HTTPException(404, "Component not found")
    project.components = remaining
    return store.save_revision(project)


@router.get("/catalog")
def get_catalog(kind: str | None = None):
    return {cid: item for cid, item in CATALOG.items() if kind is None or item["kind"] == kind}


@router.get("/agents")
def list_agents():
    return [{"name": a.name, "output": a.output} for a in AGENTS.values()]


# ---- Finance ----------------------------------------------------------------

class OptimizeRequest(BaseModel):
    target_savings_usd: float | None = Field(default=None, ge=0)
    target_savings_pct: float | None = Field(default=None, gt=0, le=100)
    apply: bool = False  # save as a new revision (verification still pending)


@router.get("/projects/{project_id}/finance/bom")
def get_bom(project_id: str, revision: int | None = None):
    return build_bom(_get(project_id, revision).components)


@router.get("/projects/{project_id}/finance/budget")
def get_budget(project_id: str, revision: int | None = None):
    p = _get(project_id, revision)
    return check_budget(build_bom(p.components), p.requirements.budget_usd, p.requirements.contingency_pct)


@router.post("/projects/{project_id}/finance/optimize")
def optimize(project_id: str, body: OptimizeRequest):
    """e.g. 'Make it 20% cheaper without reducing payload' -> target_savings_pct=20."""
    project = _get(project_id)
    target = body.target_savings_usd
    if body.target_savings_pct is not None:
        target = build_bom(project.components).total_usd * body.target_savings_pct / 100

    proposed, result = optimize_cost(project.components, target)
    response = {"result": result, "applied_revision": None}
    if body.apply and result.substitutions:
        project.components = proposed
        project.validation.append(ValidationRecord(
            check="cost_optimization_substitutions", status="pending",
            detail=f"{len(result.substitutions)} substitution(s) need torque/mass/power/fit verification.",
        ))
        response["applied_revision"] = store.save_revision(project).revision
    return response


@router.post("/projects/{project_id}/finance/tco")
def get_tco(project_id: str, body: TCOInput, revision: int | None = None):
    p = _get(project_id, revision)
    return estimate_tco(p.components, build_bom(p.components), body)


@router.get("/projects/{project_id}/finance/compare")
def compare_revisions(project_id: str, a: int, b: int):
    """Compare cost between two design revisions."""
    pa, pb = _get(project_id, a), _get(project_id, b)
    ba, bb = build_bom(pa.components), build_bom(pb.components)
    cats = sorted(set(ba.by_category_usd) | set(bb.by_category_usd))
    return {
        "revision_a": a, "revision_b": b,
        "total_usd": {"a": ba.total_usd, "b": bb.total_usd, "delta": round(bb.total_usd - ba.total_usd, 2)},
        "mass_kg": {"a": ba.total_mass_kg, "b": bb.total_mass_kg},
        "by_category_delta_usd": {
            c: round(bb.by_category_usd.get(c, 0) - ba.by_category_usd.get(c, 0), 2) for c in cats
        },
    }


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


@router.post("/projects/{project_id}/architect/chat")
def architect_chat(project_id: str, body: ChatRequest):
    """One turn of the adaptive requirements interview (Gemini)."""
    project = _get(project_id)
    try:
        out = AGENTS["architect"].run(project, message=body.message)
    except LLMUnavailable as e:
        raise HTTPException(503, f"Architect unavailable: {e}")
    except Exception as e:  # upstream LLM/network errors
        raise HTTPException(502, f"Architect model call failed: {type(e).__name__}")

    project.requirements = out["requirements"]
    if out["robot_category"]:
        project.architecture["type"] = out["robot_category"]
    project.conversation += [ChatMessage(role="user", content=body.message),
                             ChatMessage(role="architect", content=out["turn"].reply)]
    saved = store.save_revision(project)
    return {
        "reply": out["turn"].reply,
        "next_question": out["turn"].next_question,
        "ready_for_design": out["turn"].ready_for_design,
        "feasibility_concerns": out["feasibility_concerns"],
        "requirements": saved.requirements,
        "revision": saved.revision,
    }


@router.post("/projects/{project_id}/agents/finance")
def run_finance_agent(project_id: str):
    """Full finance pass: BOM + budget + optimization proposal to get within budget."""
    return AGENTS["finance"].run(_get(project_id))
