# RoboForge Engine (skeleton)

Backend for RoboForge AI. Finance-first: the Finance Engine is implemented; other agents are stubs.

## Run

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
export GEMINI_API_KEY=...        # free key: https://aistudio.google.com/apikey
export GEMINI_MODEL=gemini-3.5-flash   # optional override
.venv/bin/uvicorn roboforge.main:app --reload
# docs at http://127.0.0.1:8000/docs
```

## Layout

```
roboforge/
  models.py      RobotProject: the single shared, versioned design model
  store.py       In-memory revision store (replace with Supabase later)
  catalog.py     Curated components + critical specs per substitution group
  llm.py         Gemini wrapper (structured JSON output)
  agents.py      ArchitectAgent (Gemini) + FinanceAgent wired; others stubs
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

## Hack Knight integrations

Snowflake is intentionally not included yet. The other sponsor integrations are
ready to configure without putting a secret in source control.

### ElevenLabs: Architect replies as speech

Set these variables on the **backend only** (never in browser code):

```bash
export ELEVENLABS_API_KEY=...
export ELEVENLABS_VOICE_ID=...
# optional; defaults to eleven_multilingual_v2
export ELEVENLABS_MODEL_ID=...
```

Send a transcript to `POST /projects/{id}/voice/architect`; its `speech.text`
can then be sent to `POST /voice/synthesize`, which returns `audio/mpeg`.

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
post simulation measurements to `POST /projects/{id}/telemetry` and display
the rollups from `GET /projects/{id}/telemetry/summary`.

### Presage: consented adaptive interface

Run Presage in a supported camera client. Send only a coarse session state to
`POST /projects/{id}/adaptive-interface`, for example:

```json
{"consent": true, "state": "needs_guidance", "confidence": 0.9}
```

The backend rejects extra fields, does not accept video or vital-sign values,
and does not store the signal. It returns temporary UI recommendations such as
plain-language explanations and a slower voice speed.
