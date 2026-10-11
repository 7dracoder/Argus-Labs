# Robot-part CAD integration

Argus Labs uses the MIT-licensed [earthtojake/text-to-cad](https://github.com/earthtojake/text-to-cad)
runtime (`cadgen==0.7.20`). The useful upstream patterns are parametric model
factories, declared STEP/STL/GLB exports, cached builds, and validation of saved
geometry. The runtime uses build123d/OpenCascade. It does not provide an LLM or
a text-to-CAD HTTP endpoint; Argus Labs' GLM 5.3 client interprets text.
This integration is original application code; the upstream runtime is an
optional dependency rather than a vendored copy of its plugin or viewer.

## Install and run on Windows

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,cad,integrations]"
.\.venv\Scripts\python.exe -m uvicorn roboforge.main:app --reload
```

If the launcher cannot find Python, use your installed Python's absolute path.
CAD generation uses no external CAD account or key. Set `GLM_API_KEY` in `.env` only
for the optional natural-language input. Use `/cad/status` to check the installed
runtime version; Swagger UI is at `http://127.0.0.1:8000/docs`.

## Generate a part

First create a project with `POST /projects` or `POST /projects/demo`. Send this
to `POST /projects/{id}/agents/mechanical`:

```json
{
  "spec": {
    "name": "Shoulder arm link",
    "kind": "arm_link",
    "length_mm": 160,
    "width_mm": 30,
    "thickness_mm": 6,
    "hole_diameter_mm": 4,
    "hole_inset_mm": 10,
    "material": "petg"
  },
  "estimated_unit_cost_usd": 8
}
```

Or supply `prompt` instead of `spec`:

```json
{"prompt": "Make a PETG arm link 160 mm long, 30 mm wide and 6 mm thick, with two 4 mm pivot bores 10 mm from the ends."}
```

The supported templates are a four-hole chassis plate, two-hole arm link, and
an L-shaped motor bracket with four base holes. The bracket's upright has no
motor-specific mounting holes; those require a verified motor interface.
All CAD dimensions are mm, using XY as the base plane and +Z up. GLB uses the
runtime's glTF coordinate convention; consumers should use glTF scene units.
Prompts produce validated numeric parameters, not Python to execute. Unsupported
requests can yield proposed simplified parts, explicitly listed as assumptions;
review these before treating the result as your requested design.

The response includes the spec, assumptions, measurements, revision, and links
to STEP, STL, GLB, source, spec JSON, and the geometry report. Geometry checks
reopen the saved STEP and check valid BREP, a single positive-volume solid, the
requested envelope within 0.01 mm, bore diameters/positions, and expected volume.
Mass is a solid-material estimate excluding infill and hardware. Structural
strength, motor compatibility, printability, and assembly clearance are pending.

An optional `estimated_unit_cost_usd` puts the generated part and measured mass
into the BOM. No fabrication quote is invented when no price is supplied.
To edit a part, pass `base_design_id` and a complete new spec, or a prompt such
as "Make this arm link 10 cm longer". A priced part keeps its component ID and
price when edited unless a new estimate is supplied. Historical CAD files remain
downloadable from the revision-specific response links. Reassess the price after
dimension/material changes.

Generate downloadable sample parts locally without credentials:

```powershell
.\.venv\Scripts\python.exe examples/cad_demo.py
# Add --snapshot to render each STEP for visual review.
# Use --preview for an offline polygon preview if Chromium cannot launch.
```

## Storage and execution

Outputs live under `artifacts/cad/{content_hash}` (ignored by Git). Set
`ROBOFORGE_CAD_ROOT` to use another data directory. The hash includes the spec,
template/worker code and runtime version; cached files are SHA-256 checked before
reuse. A worker process bounds build time to 180 seconds and runs reviewed
factories only. It is not a security sandbox for arbitrary generated code. CAD
runtime telemetry and automatic update checks are disabled for these workers.
Projects still use the existing in-memory store; restarting the API loses project
attachments even though CAD files persist. This prototype performs builds in a
request worker; use a durable queue and persistent projects before scaling.

## Verification and review

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Tests generate all three templates, inspect actual geometry, exercise caching,
edit a priced component, check revision-bound downloads, and verify that failures
do not create design revisions. CAD tests skip when the optional runtime is absent.
For a visual check, use the installed runtime's viewer or snapshot command:

```powershell
$env:CADGEN_TELEMETRY = "0"
$env:CADGEN_UPDATE_CHECK = "0"
.\.venv\Scripts\cadgen.exe step snapshot artifacts/cad/<hash>/STEP/part.step artifacts/review.png
```

See the [upstream model contract](https://github.com/earthtojake/text-to-cad/blob/main/skills/cad/references/step-generation.md)
and [export documentation](https://github.com/earthtojake/text-to-cad/blob/main/skills/cad/references/supported-exports.md)
for additional runtime features. Argus Labs currently integrates part generation;
assembly kinematics, vendor STEP lookup, URDF, and fabrication ordering are future extensions.
