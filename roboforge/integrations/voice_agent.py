"""Live voice conversation with Forge via the ElevenLabs Agents platform.

The backend owns the agent definition: it creates a private agent on first use,
keeps its configuration in sync (by content hash), and hands the browser a
short-lived signed WebSocket URL. The API key never reaches the browser.

The agent acts on the design through *client tools* that run in the browser and
call this backend's normal, revisioned API (budget, brief, parts, cost).
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from threading import Lock

import httpx

from roboforge.archetypes import ARCHETYPES

BASE = "https://api.elevenlabs.io/v1"
STATE_FILE = Path(os.environ.get("ROBOFORGE_CAD_ROOT", "artifacts/cad")).resolve().parent / "voice_agent.json"
AGENT_NAME = "Argus Labs · Forge voice copilot"

PROMPT = """# Personality
You are Forge, the voice copilot of Argus Labs, a robot design workspace. You are calm, practical and brief.

# Environment
You talk with a person who is designing a robot in the Argus Labs web app. They may be a beginner.
The current robot, as of the start of this call:
{{robot_context}}

# Tone
- Speak in one to three short sentences. No lists, markdown or code.
- Say money naturally, for example "about two thousand four hundred dollars".
- Use plain words; explain jargon in a few words when you must use it.

# Goal
Help the person get the best robot for their needs and budget.
1. If no robot exists yet, ask what it should do and the budget, then call start_new_robot.
2. Before answering questions about cost, parts or performance, call get_robot_status for fresh numbers. This step is important.
3. To change the budget call set_budget; to change payload, movement, runtime, the task, the robot type or the
   contingency reserve call update_brief. Both rebuild the robot.
4. Call make_it_cheaper when they want to save money without losing capability. Call find_where_to_buy when
   they ask where or how to buy the parts; say which store has most of them and that prices must be checked.
5. Call highlight_part when they ask about or want to see a specific part; it also says what the part holds,
   powers or drives, how hard it is loaded, and what it could be swapped for.
6. To change one part (cheaper, stronger, lighter, the best one, a named model, or remove it) call edit_part.
   The app tells you which part the user selected in the 3D view; "this" or "it" means that part. Tell them
   the result from the tool's reply, including any warning that a part is too weak.
7. Before calling build_custom_part, say what you will build and get a yes. This step is important.
   Use exact millimetres and a material when the user gives them; otherwise a size preset.
8. Call download_file when they want a file: whole-robot STEP, GLB or build report, the parts list as CSV,
   or a custom part's STEP, STL, GLB or check report.
9. Call set_view to show the whole robot or a custom part, turn the 3D view to front, side, top or back,
   or close the part panel. Call open_robot to reopen an earlier robot from this session by name.
10. Call show_assembly when they ask how to build or assemble it, which wires to use, or what to 3D-print.
    Pass a step number to jump to that step. Read out only the step they asked about.

# Guardrails
- Only use numbers returned by the tools. Never invent prices, specs or test results.
- Designs are estimates: sizing, fit and safety still need human review before building.
- You cannot control real hardware or place orders.
"""

FIRST_MESSAGE = "Hi, I'm Forge. Tell me what your robot should do, or ask me about the current design."


def _tool(name: str, description: str, properties: dict | None = None, required: list[str] | None = None,
          timeout: int = 60) -> dict:
    return {"type": "client", "name": name, "description": description, "expects_response": True,
            "response_timeout_secs": timeout,
            "parameters": {"type": "object", "properties": properties or {}, "required": required or []}}


TOOLS = [
    _tool("get_robot_status", "Get the current robot: name, type, tier, performance, budget, projected cost, "
          "parts with prices, warnings and the next upgrade. Call before answering cost or part questions.",
          timeout=20),
    _tool("start_new_robot", "Create and design a brand-new robot from a plain-language description and budget.",
          {"description": {"type": "string", "description": "What the robot should do, in the user's words"},
           "budget_usd": {"type": "number", "description": "Budget in US dollars, e.g. 2500"}},
          ["description", "budget_usd"], timeout=90),
    _tool("set_budget", "Change the budget. The robot is rebuilt with the best parts that fit.",
          {"budget_usd": {"type": "number", "description": "New budget in US dollars, 300 to 20000"}},
          ["budget_usd"], timeout=90),
    _tool("update_brief", "Change requirements and rebuild the robot. Only include fields the user changed.",
          {"payload_kg": {"type": "number", "description": "Heaviest object to carry, kilograms"},
           "mobility": {"type": "string", "enum": ["wheeled", "fixed"],
                        "description": "wheeled to drive around, fixed to stay in place"},
           "runtime_hours": {"type": "number", "description": "Battery runtime target in hours"},
           "description": {"type": "string", "description": "Updated description of the task"},
           "robot_type": {"type": "string", "enum": ["automatic", *ARCHETYPES],
                          "description": "Force a body plan: " + ", ".join(f"{k} = {a.label}" for k, a in ARCHETYPES.items())
                          + "; automatic lets Argus choose"},
           "contingency_pct": {"type": "number", "description": "Reserve added on top of parts cost, percent (0 to 50)"}},
          [], timeout=90),
    _tool("make_it_cheaper", "Swap to cheaper parts with equal or better key specs. If over budget, fits the budget.",
          timeout=60),
    _tool("find_where_to_buy", "Search robotics stores for every part and add buy links to the parts list. Keeps "
          "most parts at one store unless another is clearly cheaper. Returns the main store and each part's store.",
          timeout=45),
    _tool("highlight_part", "Highlight a part in the 3D view and open its panel. Returns price, what it holds, "
          "powers or drives, what it is mounted on, load versus rating, and swap options.",
          {"part_name": {"type": "string", "description": "Part name or type, e.g. battery, camera, shoulder servo"}},
          ["part_name"], timeout=15),
    _tool("edit_part", "Change one part: swap it (cheaper, stronger, lighter, best, or a named model) or remove it. "
          "Uses the part selected in the 3D view unless part_name is given. Rebuilds the 3D model.",
          {"part_name": {"type": "string", "description": "Optional part name or type; omit for the selected part"},
           "instruction": {"type": "string", "description": "The change in the user's words, e.g. make it cheaper"}},
          ["instruction"], timeout=90),
    _tool("build_custom_part", "Build a printable CAD part and add it to the robot. Confirm with the user first.",
          {"kind": {"type": "string", "enum": ["arm_link", "chassis_plate", "motor_bracket"],
                    "description": "arm_link for arm bones, chassis_plate for the top deck, motor_bracket for wheel motors"},
           "size": {"type": "string", "enum": ["S", "M", "L"], "description": "Small, medium or large preset"},
           "length_mm": {"type": "number", "description": "Exact length in mm (10 to 1000); overrides the preset"},
           "width_mm": {"type": "number", "description": "Exact width in mm (10 to 1000); overrides the preset"},
           "thickness_mm": {"type": "number", "description": "Exact thickness in mm (1 to 50); overrides the preset"},
           "material": {"type": "string", "enum": ["petg", "pla", "aluminum"], "description": "Default petg"}},
          ["kind"], timeout=120),
    _tool("download_file", "Download a file to the user's computer.",
          {"file": {"type": "string", "enum": ["robot_step", "robot_glb", "build_report", "parts_csv",
                                               "part_step", "part_stl", "part_glb", "part_report"],
                    "description": "robot_* is the whole robot; part_* is a custom part"},
           "part_name": {"type": "string", "description": "Which custom part, e.g. arm link; omit for the latest"}},
          ["file"], timeout=20),
    _tool("set_view", "Control the 3D view.",
          {"view": {"type": "string", "enum": ["whole_robot", "custom_part"], "description": "What to show"},
           "angle": {"type": "string", "enum": ["front", "side", "back", "top", "default"],
                     "description": "Turn the camera to this side"},
           "close_panel": {"type": "boolean", "description": "Close the selected part's panel"}},
          [], timeout=20),
    _tool("open_robot", "Reopen an earlier robot from this session.",
          {"name": {"type": "string", "description": "Words from the robot's name or description"}},
          ["name"], timeout=30),
    _tool("show_assembly", "Open the assembly guide: build steps shown in 3D, parts to 3D-print and the wiring "
          "table. Returns the steps, the printed parts and the main wiring.",
          {"step": {"type": "number", "description": "Optional step number to show, starting at 1"}},
          [], timeout=45),
]


def agent_config() -> dict:
    voice_id = os.environ.get("ELEVENLABS_VOICE_ID")
    tts = {"voice_id": voice_id} if voice_id else {}
    if os.environ.get("ELEVENLABS_AGENT_TTS_MODEL"):
        tts["model_id"] = os.environ["ELEVENLABS_AGENT_TTS_MODEL"]
    return {
        "name": AGENT_NAME,
        "tags": ["argus-labs"],
        "conversation_config": {
            "agent": {
                "first_message": FIRST_MESSAGE,
                "language": "en",
                "dynamic_variables": {"dynamic_variable_placeholders": {"robot_context": "No robot yet."}},
                "prompt": {
                    "prompt": PROMPT,
                    "llm": os.environ.get("ELEVENLABS_AGENT_LLM", "gemini-3.5-flash"),
                    "temperature": 0.3,
                    "tools": TOOLS,
                    "built_in_tools": {"end_call": {
                        "name": "end_call", "description": "End the conversation when the user says goodbye.",
                        "params": {"system_tool_type": "end_call"}}},
                },
            },
            "tts": tts,
            "turn": {"turn_eagerness": "normal", "silence_end_call_timeout": 90},
            "conversation": {
                "max_duration_seconds": int(os.environ.get("ELEVENLABS_AGENT_MAX_SECONDS", "600")),
                "client_events": ["audio", "interruption", "user_transcript", "agent_response",
                                  "agent_response_correction", "client_tool_call", "vad_score"],
            },
        },
        "platform_settings": {
            "auth": {"enable_auth": True},  # private: browser needs a backend-signed URL
            "call_limits": {"daily_limit": int(os.environ.get("ELEVENLABS_AGENT_DAILY_LIMIT", "100"))},
        },
    }


class VoiceAgentUnavailable(RuntimeError):
    pass


class VoiceAgentManager:
    def __init__(self) -> None:
        self._lock = Lock()

    @property
    def api_key(self) -> str | None:
        return os.environ.get("ELEVENLABS_API_KEY")

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _call(self, method: str, path: str, **kwargs) -> dict:
        if not self.api_key:
            raise VoiceAgentUnavailable("Set ELEVENLABS_API_KEY in .env.")
        try:
            with httpx.Client(timeout=30, follow_redirects=False) as client:
                response = client.request(method, f"{BASE}/{path}", headers={"xi-api-key": self.api_key}, **kwargs)
        except httpx.RequestError:
            raise VoiceAgentUnavailable("ElevenLabs could not be reached.") from None
        if not response.is_success:
            import logging
            logging.getLogger(__name__).error("ElevenLabs agents %s %s -> %s: %s", method, path,
                                              response.status_code, response.text[:800])
            raise VoiceAgentUnavailable(f"ElevenLabs rejected the voice agent request ({response.status_code}). "
                                        "Check key permissions (Agents) and credits.")
        return response.json() if response.content else {}

    def _state(self) -> dict:
        try:
            return json.loads(STATE_FILE.read_text())
        except (OSError, ValueError):
            return {}

    def ensure_agent(self) -> str:
        """Return the agent id, creating or updating the managed agent if its config changed."""
        explicit = os.environ.get("ELEVENLABS_AGENT_ID")
        config = agent_config()
        digest = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
        with self._lock:
            state = self._state()
            agent_id = explicit or state.get("agent_id")
            # An agent id supplied in .env belongs to the user: use it as-is, never overwrite it.
            if explicit:
                return explicit
            if agent_id and state.get("config_hash") == digest:
                return agent_id
            if agent_id:
                try:
                    self._call("PATCH", f"convai/agents/{agent_id}", json=config)
                except VoiceAgentUnavailable:
                    agent_id = None  # deleted remotely; recreate below
            if not agent_id:
                agent_id = self._call("POST", "convai/agents/create", json=config)["agent_id"]
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            STATE_FILE.write_text(json.dumps({"agent_id": agent_id, "config_hash": digest}))
            return agent_id

    def signed_url(self) -> dict:
        agent_id = self.ensure_agent()
        payload = self._call("GET", "convai/conversation/get-signed-url", params={"agent_id": agent_id})
        url = payload.get("signed_url")
        if not isinstance(url, str) or not url.startswith("wss://"):
            raise VoiceAgentUnavailable("ElevenLabs returned no signed conversation URL.")
        return {"signed_url": url, "agent_id": agent_id}


voice_agent = VoiceAgentManager()
