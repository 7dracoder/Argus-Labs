# Argus Labs

Robot design workspace and backend. The Python package is still named `roboforge`. Architect, Finance, and Mechanical agents are implemented;
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
# Configure GEMINI_API_KEY; retain BASETEN_API_KEY or GLM_API_KEY for quota backup.
.venv/bin/uvicorn roboforge.main:app --reload
# docs at http://127.0.0.1:8000/docs
```

## Layout

```
roboforge/
  models.py      RobotProject: the single shared, versioned design model
  store.py       In-memory revision store (replace with Supabase later)
  catalog.py     Curated components + critical specs per substitution group
  llm.py         Gemini structured output with optional GLM quota fallback
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
or a numeric `spec` (no credentials needed). It produces STEP, STL and GLB with
saved-geometry checks, attaches the files to a project revision, and can add a
user-priced generated component to the finance BOM.
See [CAD setup and examples](docs/text-to-cad.md) for Windows commands, supported
templates, editing, downloads, limitations, and tests.

Architect chat, backend voice and CAD interpretation share the selected provider.
To use Baseten-hosted GLM directly, set `BASETEN_API_KEY` (or the existing `GLM_API_KEY`),
`LLM_PROVIDER=baseten`, `GLM_MODEL=zai-org/GLM-5.3` and
`GLM_BASE_URL=https://inference.baseten.co/v1`. No Z.ai key is needed. Direct
Z.ai remains available with `LLM_PROVIDER=glm` and its own key/model/endpoint.
The client uses JSON
mode and validates responses with the same Pydantic schemas used by the agents.
Live calls require your key. The local configuration now uses `LLM_PROVIDER=gemini`,
`GEMINI_API_KEY` and `GEMINI_MODEL=gemini-3.6-flash` as primary. Set
`LLM_FALLBACK_PROVIDER=baseten` to keep the existing Baseten-hosted GLM as backup.
Gemini HTTP 429 quota/rate-limit responses trigger the backup for the current
request and a `LLM_FALLBACK_COOLDOWN_SECONDS=60` cooldown, after which Gemini is
tried again. No environment variables are changed by failover. Authentication,
access, transport and malformed-output errors do not trigger paid backup calls.
Both providers must still return schema-valid output. Integration status reports
the active provider and cooldown without credentials. A configured backup may
use Baseten credits; this is not a guarantee of free usage on either provider.
Keep Gemini's project on the free tier if you want to avoid Google charges:
the app detects quota errors, not remaining free credits or billing status.
Leave `LLM_FALLBACK_PROVIDER` empty to disable failover. Restart after editing `.env`.

## Website

Reference research uses You.com Web Search when `RESEARCH_PROVIDER=you` and
`YDC_API_KEY` is set in the ignored root `.env`. Retrieved titles, links and
snippets ground the concept step; thumbnails are not treated as visual evidence.
The adapter follows the [You.com Search API](https://you.com/docs/api-reference/search/v1-search)
and sends credentials only in the backend's `X-API-Key` header.
Search status is saved with the concept so a failed search is not a silent pass.
To switch later, set `RESEARCH_PROVIDER=tavily` and `TAVILY_API_KEY`, then restart.
Tavily also supplies described images. Web results are untrusted reference data,
not instructions or verified engineering specifications.

Open `http://127.0.0.1:8765` and describe a robot in plain words with a budget.
`POST /projects/{id}/design/auto` (`roboforge/design.py`) picks the cheapest catalog
parts that meet torque, energy and load needs, then fits the budget.
`GET /projects/{id}/assembly` (`roboforge/assembly.py`) lays out the whole robot
for the 3D view; generated CAD parts (deck plate, arm links, motor brackets) are
placed as their real GLB geometry. The layout is illustrative, not fit-checked.
`GET /projects/{id}/robot/{glb|step|report}` (`roboforge/cad/robot.py`) builds the
whole robot as a real B-rep model with text-to-cad's cadgen/build123d kernel:
labelled, coloured parts exported to STEP and GLB, cached by layout hash. Catalog
parts are representative models, not vendor CAD.

## Local robotics design studio

Run the backend, then open `http://127.0.0.1:8765`:

```powershell
.\.venv\Scripts\python.exe -m uvicorn roboforge.main:app --host 127.0.0.1 --port 8765
```

The frontend is buildless HTML/CSS/JS served by FastAPI. The robot-first studio
uses vendored Three.js to display native CAD models, with eight selectable body
plans, orbit/zoom, optional rotation and fullscreen. Nothing loads from a CDN.
The design-review viewport adds front/side/top cameras, cover inspection and a
reversible exploded-view slider. Explosion groups solids by CAD assembly node;
it only moves the display, never modifies exported geometry or assembly steps.
Motion defaults to off, respects reduced-motion settings and stops rendering
when the viewport is offscreen. Styling is in `roboforge/web/studio.css`.

**Next: how to assemble** opens the same revision's staged 3D build guide, print
downloads, purchased parts and wiring table. Prototype fit/safety limitations
remain visible. Projects reset on ordinary server restarts; keep the app local.
For a planned development restart, preserve every revision before stopping the
old server, then restore with a new, ignored recovery snapshot:

```powershell
.\.venv\Scripts\python.exe -m examples.preview --capture http://127.0.0.1:8765 --state artifacts/dev/recovery.json
# Stop the old server before running the following command.
.\.venv\Scripts\python.exe -m examples.preview --restore --state artifacts/dev/recovery.json --port 8765
```

Snapshots contain project data, not API configuration; protect them locally.
This manual helper is not durable production storage and refuses to overwrite
an existing snapshot. Choose a new snapshot name for each planned restart.

**Run guided E2E demo** under Advanced
creates a sample project, generates an arm-link CAD export with an $8 estimate,
updates the BOM, writes two labelled development samples to Tiger, asks the
configured Forge copilot for a spoken summary, and transcribes that generated
speech with ElevenLabs. It uses small vendor credits. Downloads are real STEP,
STL, GLB, and geometry reports. Catalog components are representative CAD, not
manufacturer-certified models.

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

## Financial research for robotics analysts

The design workspace includes **Investment research**, built for the photo's
Diameter AI for Finance general track. An analyst can investigate robotics and
automation businesses, compare public filing revenue, then stress-test the
ownership economics of the current robot revision. The research question,
estimated annual savings and daily operating hours are editable. No trading
accounts or private financial datasets are used.

`POST /projects/{id}/finance/research?revision=N` returns Teradyne and NVIDIA
annual revenue, demand research flags, source links, an optional AI note with
validated citation IDs, three savings scenarios, and a downloadable report.
The AI uses the existing configured Gemini or GLM adapter. Arithmetic, scenarios
and evaluation are calculated in Python. A provider failure is visible and
preserves the calculated report. Research never modifies the robot design.

The default snapshot is a deliberately historical dataset collected from public
annual filings, with ten records through Teradyne FY2024 and NVIDIA FY2025.
It is not current share prices or a robotics segment revenue dataset. Every row
links to its public source, and the snapshot's `filed` value identifies that
source document, which may contain comparative prior-year figures.

Live mode uses the [SEC Company Facts API](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
with an identifying `SEC_USER_AGENT`, a 15-minute cache and serialized retrieval.
The adapter filters annual USD durations, rejects quarterly values and malformed
provenance, selects periods by actual end date instead of a comparative fiscal
label, and retains the first available filing observation for each period.
If SEC access is blocked, the site reports it and offers the explicit historical
snapshot. It never silently labels the snapshot as live data.

The evaluation compares a next-period revenue trend estimate with an
unchanged-revenue baseline over held-out annual periods. Both MAEs and the fold
values are visible, including cases where the baseline wins. The snapshot test
is retrospective and does not claim to reconstruct what an investor knew at
each date. Live folds filter filing availability. Neither evaluates stock
returns or the language model's predictive accuracy.

Run the normal test suite and browser check against a local server:

```bash
.venv/bin/python -m unittest discover -s tests -v
# Playwright and Chrome must be available to Node; NODE_PATH can use bundled packages.
ARGUS_TEST_URL=http://127.0.0.1:8765 ARGUS_EXPECT_AI=1 node examples/studio_e2e.mjs
```

The browser check covers the white theme, parts list, real CAD export, cost
optimization, cited research, report download, assembly guide, mobile overflow
and a natural-language design. Screenshots and results go to ignored
`artifacts/dev/studio-e2e/`. It uses one configured AI research request and a
natural-language design request; microphone and camera capture are not used.

## Sponsor integration setup

Snowflake is intentionally not included yet. The other sponsor integrations are
ready to configure without putting a secret in source control.

See [Sponsor setup and Forge voice agent](docs/sponsor-setup.md) for the configured
free Tiger database, speech input/output, the consented native Presage bridge,
live verification results, and remaining credential requirements.

### Live voice conversation ("Talk to Forge")

The bar at the top of the site starts a real-time, hands-free conversation using
ElevenLabs Agents (`roboforge/integrations/voice_agent.py`, `roboforge/web/live.js`).
On first use the backend creates a private agent (Gemini via ElevenLabs, your
`ELEVENLABS_VOICE_ID`), keeps it in sync by config hash, and returns a short-lived
signed WebSocket URL from `POST /voice/live/session`. The agent changes the design
through browser client tools that call the normal API: `get_robot_status`,
`start_new_robot`, `set_budget`, `update_brief`, `make_it_cheaper`,
`highlight_part`, `build_custom_part` (asks for confirmation first). The SDK and
its audio worklets are vendored in `roboforge/web/vendor/` so the CSP stays strict.

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

### Assembly and printable parts

After building, choose **Next: how to assemble** for staged 3D steps, from/to
wiring routes, wire gauges, connectors, estimated fuse ratings, tools and a
buy/fabricate list. **3D-print parts** goes straight to the print list. Open-deck
robots get dimensioned battery/computer covers; the tracked explorer gets a
printable computer cover, while its battery stays in the purchased hull.
Closed-body robots retain their purchased housing. **Inspect internals** hides
covers for inspection; covers are visible by default.

Each supported print has STL/STEP downloads, material, orientation, slicer
settings and a 220 × 220 × 250 mm printer-envelope check. Large parts are explicitly
not pre-split. Downloads and the offline JSON assembly plan are pinned to the
guide's project revision. Purchased batteries, motors and housings are not STL
printable merely because the preview includes them. Geometry checks are not
strength, thermal, fit or electrical certification: verify datasheets and obtain
qualified review before building or applying power.

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
