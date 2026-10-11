# RoboForge Engine (skeleton)

Backend for RoboForge AI. Architect, Finance, and Mechanical agents are implemented;
the Mechanical Agent generates parametric robot parts through text-to-cad's cadgen runtime.

## Run

Edit the root `.env` file to add your API keys and connection settings. The
backend loads it automatically before initializing agents and sponsor clients;
existing shell/deployment variables take precedence. Restart after editing.
`.env` and `.env.*` are ignored by Git except for the secret-free `.env.example`.
On a fresh clone, copy `.env.example` to `.env`. The native Presage bridge reads
its key from the same file; Snowflake remains excluded.

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
# Configure BASETEN_API_KEY or GLM_API_KEY in .env for Baseten-hosted GLM 5.3.
.venv/bin/uvicorn roboforge.main:app --reload
# docs at http://127.0.0.1:8000/docs
```

## Layout

```
roboforge/
  models.py      RobotProject: the single shared, versioned design model
  store.py       In-memory revision store (replace with Supabase later)
  catalog.py     Curated components + critical specs per substitution group
  llm.py         GLM 5.3 structured output; configurable Gemini alternative
  agents.py      Architect (LLM), Mechanical (cadgen), Finance; other agents are stubs
  cad/           Part templates, dimension checks, CAD worker and export cache
  api.py         HTTP routes
  finance/
    bom.py       Itemized BOM, category subtotals, mass, lead time
    budget.py    Budget check with contingency reserve
    optimizer.py Cheaper substitutions that keep critical specs (torque, Wh...)
    lifetime.py  TCO, cost per hour/task, payback, ROI
```

## Try it

```bash
curl -X POST localhost:8000/projects/demo                     # $2,500 budget, starts over budget
curl -X POST localhost:8000/projects/<id>/architect/chat \
  -H 'content-type: application/json' -d '{"message": "A robot that carries 2 kg around my flat, $2,500"}'
curl localhost:8000/projects/<id>/finance/budget
curl -X POST localhost:8000/projects/<id>/finance/optimize \
  -H 'content-type: application/json' -d '{"target_savings_pct": 20, "apply": true}'
curl "localhost:8000/projects/<id>/finance/compare?a=1&b=2"
curl -X POST localhost:8000/projects/<id>/finance/tco \
  -H 'content-type: application/json' -d '{"tasks_per_day": 20, "annual_savings_usd": 1500}'
```

Notes: catalog prices are placeholders, not quotes. Optimizer output is marked
`verification: pending` because agents propose and independent checks verify.
The API has no authentication yet; don't expose it publicly.

## Robot part CAD

Install `pip install -e ".[cad]"`, then use
`POST /projects/{id}/agents/mechanical` with a natural-language `prompt` (GLM 5.3)
or a numeric `spec` (no credentials needed). Six reviewed templates cover chassis
plates, arm links, motor brackets, wheel hubs, gripper jaws, and sensor mounts.
`GET /projects/{id}/cad/suggest` picks a signature part from the robot brief so
different robots do not reuse the same blank. It produces STEP, STL and GLB with
saved-geometry checks, attaches the files to a project revision, and can add a
user-priced generated component to the finance BOM.
See [CAD setup and examples](docs/text-to-cad.md) for Windows commands, supported
templates, editing, downloads, limitations, and tests.

The project's `.env` selects Baseten-hosted GLM for Architect chat, voice and
CAD interpretation. Set `BASETEN_API_KEY` (or the existing `GLM_API_KEY`),
`LLM_PROVIDER=baseten`, `GLM_MODEL=zai-org/GLM-5.3` and
`GLM_BASE_URL=https://inference.baseten.co/v1`. No Z.ai key is needed. Direct
Z.ai remains available with `LLM_PROVIDER=glm` and its own key/model/endpoint.
The client uses JSON
mode and validates responses with the same Pydantic schemas used by the agents.
Live calls require your key. Later, set `LLM_PROVIDER=gemini` and `GEMINI_API_KEY`
to switch providers; `GEMINI_MODEL` remains configurable.

## Minimal local frontend

Run the backend, then open `http://127.0.0.1:8765`:

```powershell
.\.venv\Scripts\python.exe -m uvicorn roboforge.main:app --host 127.0.0.1 --port 8765
```

The frontend is buildless HTML/CSS/JS served by FastAPI. **Run guided E2E demo**
creates a sample project, generates an arm-link CAD export with an $8 estimate,
updates the BOM, writes two labelled development samples to Tiger, asks the
Baseten-hosted Forge copilot for a spoken summary, and transcribes that generated
speech with ElevenLabs. It uses small vendor credits. Downloads are real STEP,
STL, GLB, and geometry reports; the inline preview is only a schematic.

Typed chat, custom projects, reviewed CAD templates, CAD proposals with explicit
confirmation, and manual guided-pacing preview are available. Microphone input
requires a separate consent checkbox, a click, and browser permission; recording
is capped at 15 seconds. Camera capture is disabled in the browser. The native
Presage bridge remains separate; the pacing preview is synthetic, not a measured
mental state. No keys or recordings are stored in the browser. Projects still
reset when the Python server restarts. Keep this unauthenticated prototype local.

Speech/transcription may misread numbers; the deterministic BOM and budget are
authoritative. The demo verifies the pipeline, not speech accuracy or engineering
safety. Frontend source is in `roboforge/web/`.

## Sponsor integration setup

Snowflake is intentionally not included yet. The other sponsor integrations are
ready to configure without putting a secret in source control.

See [Sponsor setup and Forge voice agent](docs/sponsor-setup.md) for the configured
free Tiger database, speech input/output, the consented native Presage bridge,
live verification results, and remaining credential requirements.

### ElevenLabs: Forge robot-design voice copilot

Set these variables on the **backend only** (never in browser code):

```bash
export ELEVENLABS_API_KEY=...
export ELEVENLABS_VOICE_ID=SAz9YHcvj6GT2YYXdXww  # River (configured in .env)
export ELEVENLABS_MODEL_ID=eleven_flash_v2_5
export ELEVENLABS_STT_MODEL_ID=scribe_v2
```

Use `POST /projects/{id}/voice/agent` for GLM-powered, project-aware replies with
ElevenLabs speech. `POST /projects/{id}/voice/agent/audio?consent=true` accepts a
short recording directly. `GET /voice/agent` describes Forge's profile.
The earlier `/voice/architect` and `/voice/synthesize` endpoints still work.

### Tiger Data: simulation telemetry

Without credentials, telemetry endpoints use in-memory development storage.
For Tiger Cloud, install the optional driver and set the PostgreSQL connection
string (do not commit it):

```bash
pip install -e ".[integrations]"
export TIGER_DATABASE_URL=postgresql://...
```

Call `POST /integrations/tiger/setup` once. It creates a
`roboforge_telemetry` hypertable and a one-minute continuous aggregate. Then
post simulation measurements to `POST /projects/{id}/telemetry`. Use `/telemetry/summary`
for overall statistics and `/telemetry/timeseries` for minute rollups.
`GET /integrations/tiger/health` verifies the connection and schema without exposing secrets.

### Presage: consented adaptive interface

Use the installed bridge in `clients/presage` with `SMARTSPECTRA_API_KEY` from
`.env`; it starts a camera only with an explicit `--consent` flag. Send only a coarse session state to
`POST /projects/{id}/adaptive-interface`, for example:

```json
{"consent": true, "state": "needs_guidance", "confidence": 0.9}
```

The backend rejects extra fields, does not accept video or vital-sign values,
and does not store the signal. It returns temporary UI recommendations such as
plain-language explanations and a slower voice speed. Pass that current-session
signal to voice turns through `interaction` to apply actual speech pacing.
