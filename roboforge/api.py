"""HTTP API: projects, catalog and finance endpoints."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os

from fastapi import APIRouter, HTTPException, Query, Request, Response
from starlette.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from typing import Literal
from pydantic import BaseModel, Field

from roboforge.agents import AGENTS
from roboforge.catalog import CATALOG, DEMO_BUILD, make_component
from roboforge.finance import TCOInput, build_bom, check_budget, estimate_tco, optimize_cost
from roboforge.llm import LLMResponseError, LLMUnavailable, llm_status
from roboforge.voice import VoiceRequest, profile as voice_profile, respond as voice_respond
from roboforge.models import ChatMessage, Component, Requirements, RobotProject, ValidationRecord
from roboforge.store import store
from roboforge.integrations.elevenlabs import ElevenLabsUnavailable, elevenlabs
from roboforge.integrations.presage import PresageInteractionSignal, recommended_interface
from roboforge.integrations.tiger import TelemetryEvent, TigerUnavailable, tiger
from roboforge.cad.engine import ARTIFACTS, CADBuildFailed, CADUnavailable, root_directory, runtime_status
from roboforge.cad.spec import MechanicalRequest

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
    """One turn of the adaptive requirements interview using the configured LLM."""
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


@router.get("/cad/status")
def cad_status():
    return runtime_status()


@router.post("/projects/{project_id}/agents/mechanical")
def generate_mechanical_part(project_id: str, body: MechanicalRequest):
    project = _get(project_id)
    try:
        result = AGENTS["mechanical"].run(project, request=body)
    except (CADUnavailable, LLMUnavailable) as error:
        raise HTTPException(503, str(error)) from error
    except CADBuildFailed as error:
        raise HTTPException(502, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, "Invalid part proposal or base design.") from error
    except Exception as error:
        raise HTTPException(502, "Mechanical generation failed.") from error
    parts = project.manufacturing.setdefault("cad_parts", {})
    base = parts.get(body.base_design_id, {}) if body.base_design_id else parts.get(result["design_id"], {})
    result["component_id"] = base.get("component_id")
    # Attach to the costed BOM only when a fabrication estimate is supplied.
    old_component = next((c for c in project.components if c.id == result["component_id"]), None)
    price = body.estimated_unit_cost_usd
    if price is not None or old_component:
        component = Component(
            name=result["spec"]["name"], category="mechanical", kind=result["spec"]["kind"],
            source="generated", unit_cost_usd=price if price is not None else old_component.unit_cost_usd,
            specs={"mass_kg": result["geometry"]["mass_kg"]},
        )
        if old_component:
            component.id, component.quantity = old_component.id, old_component.quantity
            project.components = [component if c.id == component.id else c for c in project.components]
        else:
            project.components.append(component)
        result["component_id"] = component.id
    parts[result["design_id"]] = result
    project.validation.extend([
        ValidationRecord(check="cad_geometry", status="pass",
                         detail=f"{result['design_id']}: saved STEP topology, bounds and bore volume checked."),
        ValidationRecord(check="cad_engineering", status="pending",
                         detail="Structural load, motor fit, assembly clearance and manufacturing remain unverified."),
    ])
    saved = store.save_revision(project)
    return {**result, "revision": saved.revision, "downloads": {
        kind: f"/projects/{project_id}/cad/{result['design_id']}/{kind}?revision={saved.revision}"
        for kind in ARTIFACTS
    }}


@router.get("/projects/{project_id}/cad/{design_id}/{format}")
def download_cad(project_id: str, design_id: str,
                 format: Literal["step", "stl", "glb", "source", "spec", "report"],
                 revision: int | None = None):
    project = _get(project_id, revision)
    if design_id not in project.manufacturing.get("cad_parts", {}):
        raise HTTPException(404, "CAD design is not attached to this project revision.")
    # Identifiers generated by the engine are SHA-256; no caller-controlled file paths.
    import re
    if not re.fullmatch(r"[a-f0-9]{64}", design_id):
        raise HTTPException(404, "CAD design not found.")
    path = root_directory() / design_id / ARTIFACTS[format]
    if not path.is_file():
        raise HTTPException(404, "CAD artifact is unavailable.")
    media = {"step": "application/step", "stl": "model/stl", "glb": "model/gltf-binary",
             "source": "text/plain", "spec": "application/json", "report": "application/json"}
    return FileResponse(path, media_type=media[format], filename=path.name)


# ---- Sponsor integrations ---------------------------------------------------

class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    voice_id: str | None = Field(default=None, max_length=200)
    speed: float = Field(default=1.0, ge=0.7, le=1.2, allow_inf_nan=False)


@router.get("/integrations/status")
def integration_status():
    """Credential-safe status: never return keys, URLs, or vendor account data."""
    return {
        "elevenlabs": {"configured": elevenlabs.configured, "purpose": "Forge speech recognition and synthesis"},
        "llm": llm_status(),
        "tiger": {"configured": tiger.mode == "tiger", "mode": tiger.mode, "purpose": "simulation telemetry"},
        "presage": {
            "key_configured": bool(os.environ.get("SMARTSPECTRA_API_KEY")),
            "configured": "native camera bridge requires an explicit consented session",
            "purpose": "opt-in adaptive interface; no biometric storage",
        },
    }


@router.post("/voice/synthesize", response_class=Response)
def synthesize_speech(body: SpeechRequest):
    """Convert an Architect reply to MP3 while keeping the ElevenLabs key server-side."""
    try:
        audio = elevenlabs.synthesize(body.text, body.voice_id, body.speed)
    except ElevenLabsUnavailable as error:
        raise HTTPException(503, str(error)) from error
    return Response(content=audio, media_type="audio/mpeg", headers={"Cache-Control": "no-store"})


@router.get("/voice/agent")
def get_voice_agent():
    return voice_profile()


@router.post("/projects/{project_id}/voice/agent")
def voice_agent(project_id: str, body: VoiceRequest, response: Response):
    project = _get(project_id)
    if body.interaction and not body.interaction.consent:
        raise HTTPException(422, "Adaptive voice requires current-session consent.")
    try:
        telemetry = tiger.summary(project_id)
    except TigerUnavailable:
        telemetry = {"available": False}
    try:
        result = voice_respond(project, body, telemetry)
    except LLMUnavailable as error:
        raise HTTPException(503, str(error)) from error
    except LLMResponseError as error:
        raise HTTPException(502, str(error)) from error
    except Exception:
        raise HTTPException(502, "Voice model returned an invalid response.") from None
    response.headers["Cache-Control"] = "no-store"
    return result


async def _read_recording(request: Request, consent: bool) -> tuple[bytes, str]:
    if not consent:
        raise HTTPException(422, "Confirm consent before sending audio to ElevenLabs.")
    content_type = request.headers.get("content-type", "").split(";")[0].lower()
    if content_type not in {"audio/wav", "audio/x-wav", "audio/mpeg", "audio/mp4", "audio/webm", "audio/ogg"}:
        raise HTTPException(415, "Send a WAV, MP3, M4A, WebM, or Ogg recording as the request body.")
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > 10 * 1024 * 1024:
            raise HTTPException(413, "Recording must not exceed 10 MiB.")
        chunks.append(chunk)
    if not size:
        raise HTTPException(422, "Recording is empty.")
    return b"".join(chunks), content_type


@router.post("/voice/transcribe")
async def transcribe_voice(request: Request, response: Response, consent: bool = False):
    audio, content_type = await _read_recording(request, consent)
    try:
        result = await run_in_threadpool(elevenlabs.transcribe, audio, content_type)
    except ElevenLabsUnavailable as error:
        raise HTTPException(503, str(error)) from error
    response.headers["Cache-Control"] = "no-store"
    return result


@router.post("/projects/{project_id}/voice/agent/audio")
async def voice_agent_audio(project_id: str, request: Request, response: Response,
                            consent: bool = False):
    _get(project_id)
    transcript = await transcribe_voice(request, response, consent)
    result = await run_in_threadpool(voice_agent, project_id,
                                    VoiceRequest(message=transcript["text"]), response)
    return {**result, "transcript": transcript["text"]}


@router.post("/projects/{project_id}/voice/architect")
def voice_architect(project_id: str, body: ChatRequest):
    """Accept a speech-to-text transcript and return an Architect reply ready for TTS."""
    response = architect_chat(project_id, body)
    response["speech"] = {
        "text": response["reply"],
        "synthesis_endpoint": "/voice/synthesize",
        "cache": "disabled",
    }
    return response


@router.post("/projects/{project_id}/telemetry")
def record_telemetry(project_id: str, body: TelemetryEvent):
    """Record one simulation metric (e.g. torque_nm, battery_pct, collisions)."""
    _get(project_id)  # Return 404 instead of accepting orphaned telemetry.
    try:
        return tiger.record(project_id, body)
    except TigerUnavailable as error:
        raise HTTPException(503, str(error)) from error


@router.get("/projects/{project_id}/telemetry/summary")
def telemetry_summary(project_id: str, scenario_id: str | None = None):
    _get(project_id)
    try:
        return tiger.summary(project_id, scenario_id)
    except TigerUnavailable as error:
        raise HTTPException(503, str(error)) from error


@router.post("/integrations/tiger/setup")
def setup_tiger():
    """Initialize the Tiger hypertable and one-minute continuous aggregate."""
    try:
        tiger.initialize()
    except TigerUnavailable as error:
        raise HTTPException(503, str(error)) from error
    return {"status": "ready", "storage": "tiger", "objects": ["roboforge_telemetry", "roboforge_telemetry_1m"]}


@router.get("/integrations/tiger/health")
def tiger_health():
    return tiger.health()


@router.get("/projects/{project_id}/telemetry/timeseries")
def telemetry_timeseries(project_id: str, scenario_id: str | None = None,
                         hours: int = Query(default=24, ge=1, le=24),
                         limit: int = Query(default=300, ge=1, le=1000)):
    _get(project_id)
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    try:
        return tiger.timeseries(project_id, since, scenario_id, limit)
    except TigerUnavailable as error:
        raise HTTPException(503, str(error)) from error


@router.post("/projects/{project_id}/adaptive-interface")
def adaptive_interface(project_id: str, body: PresageInteractionSignal):
    """Map a consented Presage client signal to temporary UI settings.

    Raw camera frames, vital signs, and biometric histories are intentionally
    not accepted or persisted by this endpoint.
    """
    _get(project_id)
    try:
        recommendation = recommended_interface(body)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    return {
        "source": "presage",
        "persisted": False,
        "expires_when_session_ends": True,
        "recommendation": recommendation,
    }
