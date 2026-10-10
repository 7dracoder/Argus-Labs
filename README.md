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
