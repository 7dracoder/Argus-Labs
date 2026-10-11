# Sponsor setup and voice copilot

All local credentials belong in the ignored root `.env`. Restart the backend
after editing; existing shell/deployment variables take precedence. Do not commit
downloaded credential files, and do not put keys in a browser bundle.

## Tiger Data

The development service `roboforge-telemetry` was created on Tiger Cloud's
**Shared Free** tier in AWS US East (N. Virginia). Its PostgreSQL connection URI
has been saved to `TIGER_DATABASE_URL` with `sslmode=require`. A Tiger Cloud
management API key is not required for telemetry ingestion. The downloaded
credentials file in Downloads is also sensitive: keep it private.

Use this on a new deployment or to repeat the idempotent setup:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,integrations,cad]"
.\.venv\Scripts\python.exe -m roboforge.integrations.setup --tiger
.\.venv\Scripts\python.exe -m roboforge.integrations.setup --check
```

Setup creates `public.roboforge_telemetry`, converts it into a time-series
hypertable, adds a project/time index and the continuous aggregate
`public.roboforge_telemetry_1m`. A one-minute refresh policy processes the latest
24 hours, excluding the actively written current minute. Real-time aggregation
includes recent unmaterialized measurements. No retention/deletion policy is
installed. Measurements older than the policy window need a manual refresh
before they appear in materialized history.

- `GET /integrations/tiger/health`: credential-safe connection and schema checks.
- `POST /integrations/tiger/setup`: explicit schema setup.
- `POST /projects/{id}/telemetry`: one timestamped, timezone-aware simulation measurement.
- `GET /projects/{id}/telemetry/summary`: counts/averages/min/max by metric/unit.
- `GET /projects/{id}/telemetry/timeseries?hours=24&limit=300`: minute rollups,
  optionally filtered with `scenario_id` (maximum 1000 points).

With a blank connection URI, development uses in-memory storage and health
reports `connected=false`. A configured-but-broken database does **not** silently
fall back to memory. Remote connections require encryption; errors do not expose
the connection string. Setup affects only Argus Labs' named schema objects.
Projects themselves still use the existing in-memory revision store; this
integration persists telemetry, not the whole project model.

The connection layer now budgets eight seconds across resolved IP addresses,
rather than waiting ten seconds for each address (the current endpoint has six).
It keeps the DNS hostname for TLS/SNI, rotates candidates between checks, and
backs off connection failures for 15 seconds. The health endpoint returns safe
`error_code` and `retry_after_seconds` fields; authentication, schema, DNS, TLS
and connection timeouts are distinct. Advanced → Tiger → **Check connection**
explicitly retries (`GET /integrations/tiger/health?retry=true`). Schema setup is
offered only after a successful connection with missing schema. Configured
failures never silently write to memory.

October 11 connectivity audit: the console reports Ready, PostgreSQL 18.6 and
TimescaleDB 2.30.2. Its SQL editor confirms both telemetry objects exist. The
public endpoint on port 36579 accepts TCP but does not answer PostgreSQL SSL
negotiation from this computer, reproduced with Python and Node. Direct TLS also
fails. This is still an external connection-path blocker, not a successful app
write/read test. Try the same `.env` on another network; do not disable SSL,
reset the password, upgrade the plan, or claim in-memory samples are Tiger data.

The live verification leaves two labelled rows for a `setup-smoke-*` project.
Those are development measurements, not simulated or real robot results.

## Forge voice copilot

Forge is an application-owned, turn-based voice agent: ElevenLabs Scribe v2
transcribes, the configured GLM 5.3 adapter reasons over project context, and
ElevenLabs Flash v2.5 speaks using the calm default River voice. Gemini remains
an opt-in future provider. This is **not** a hosted ElevenAgents dashboard agent
or a full-duplex streaming call; no phone number or public server is provisioned.

The selected settings are in `.env` and the secret-free `.env.example`:

```dotenv
ELEVENLABS_API_KEY=
ELEVENLABS_VOICE_ID=SAz9YHcvj6GT2YYXdXww
ELEVENLABS_MODEL_ID=eleven_flash_v2_5
ELEVENLABS_STT_MODEL_ID=scribe_v2
```

Forge answers robot requirements, BOM/budget questions, geometry limitations,
and recorded telemetry questions using the current project revision. CAD requests
produce a validated proposal for the user to confirm through the Mechanical API;
voice turns do not change a revision, fabricate a quote, order parts, certify
engineering safety, or actuate hardware. History is supplied by the caller and
is bounded to 12 short messages. No separate voice-session database is created.

Endpoints:

- `GET /voice/agent`: profile and configuration status.
- `POST /projects/{id}/voice/agent`: JSON `message`, optional `history`, `speak`
  (default true), and current-session `interaction` signal. Returns reply,
  optional CAD proposal, revision, and base64 MP3 audio. A speech failure still
  returns the text and proposal with a sanitized `speech_error`.
- `POST /voice/transcribe?consent=true`: send an audio file directly as the body
  with its audio content type. Returns its transcript.
- `POST /projects/{id}/voice/agent/audio?consent=true`: audio-in, agent reply and
  audio-out in one request. This convenience endpoint is a single turn; use
  separate transcription plus the JSON endpoint to retain caller history.
- `POST /voice/synthesize`: JSON `text`, optional `voice_id` and `speed`.

Audio requests require explicit consent, accept WAV/MP3/M4A/WebM/Ogg, and are
capped at 10 MiB. The backend does not save recordings and uses `Cache-Control:
no-store`. ElevenLabs receives recordings/text and GLM receives project context;
vendor retention follows account policies (this does not claim vendor zero
retention). The API still has no authentication: keep it local, and add auth,
rate limiting, and deployment protections before making it public.

Example JSON voice turn:

```json
{
  "message": "Why is my current robot over budget?",
  "speak": true,
  "history": [],
  "interaction": {"consent": true, "state": "needs_guidance", "confidence": 0.9}
}
```

The interaction slows actual synthesized speech to 0.85x and requests a simpler
explanation. Below 0.8 signal confidence, adaptation falls back to standard
mode. No biometric values are sent to the LLM or Tiger database.

Live ElevenLabs TTS and transcription were verified using a synthetic Forge
greeting. The project uses **Baseten-hosted GLM 5.3**, not direct Z.ai. Set
`LLM_PROVIDER=baseten`, `GLM_BASE_URL=https://inference.baseten.co/v1` and
`GLM_MODEL=zai-org/GLM-5.3`. The saved key can remain in `GLM_API_KEY`;
`BASETEN_API_KEY` is also supported and takes precedence for this provider.
Do not send a Baseten key to Z.ai's endpoints. The earlier HTTP 401 errors
occurred at those mismatched endpoints. Baseten uses Bearer authentication and
`reasoning_effort=low`; JSON responses still receive local schema validation.
Gemini remains an explicit future switch, never a silent fallback.
See [Baseten's GLM 5.3 API setup](https://www.baseten.co/resources/changelog/glm-53-available-on-baseten/).
The generated greeting is at `artifacts/voice/forge-intro.mp3`.

## Presage camera bridge

The official SmartSpectra **Node.js** SDK 3.4.0 is installed under
`clients/presage`. Its Windows x64 native runtime was verified to load without
starting a camera. This route does not require the C++ compiler setup discussed
for the separate C++ SDK. Add your actual `SMARTSPECTRA_API_KEY` to the root
`.env`. Live camera capture and SDK metrics have now been verified with explicit
consent; stable calibration still requires a suitable measurement environment.

```powershell
cd clients/presage
npm.cmd install
npm.cmd run check             # no camera capture or API authentication
npm.cmd test
npm.cmd start -- <project-id> --consent
```

The last command starts a real camera session; read Presage's vendor privacy
terms first. It connects only to the local backend in `ROBOFORGE_API_URL`, and
Ctrl+C stops capture, destroys the SDK and resets pacing. The SDK requests only
breathing rate; SDK telemetry, accumulated output, and LLM insights are disabled.
Measurements stay in transient client memory; no raw metrics/video are sent to
Argus Labs or Tiger. Presage authentication/SDK processing has its own vendor
policies, so this does not promise an entirely offline measurement pipeline.

The bridge normalizes the SDK's percentage confidence (0–100) to the local
signal's 0–1 range exactly once, at the SDK boundary. Invalid samples are
rejected rather than clamped. The optional pacing heuristic calibrates for
60 seconds with normalized confidence >=0.8 (SDK confidence >=80).
A relative breathing-rate increase of more than 25% sustained for 15 seconds
suggests simpler/slower presentation (`needs_guidance`). This is a prototype UI
preference heuristic, not a validated stress, confusion, focus, or medical
classifier. Bad measurements/missing frames keep standard presentation; the
legacy `focused` state means standard UI, not proof of mental focus. It does not
automatically infer `needs_break`.

The bridge posts coarse signals and prints UI recommendations only. A future
frontend should apply those recommendations and pass the current coarse signal
to each voice request through `interaction`; the backend intentionally does not
retain a global biometric or pacing state. The browser frontend is not built yet.

## Verification

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
# Optional live checks: consumes API credits and writes labelled test telemetry.
.\.venv\Scripts\python.exe examples/sponsor_smoke.py --tiger --voice
# Real localhost HTTP checks; creates labelled development telemetry and uses credits.
.\.venv\Scripts\python.exe examples/e2e.py
# Explicit opt-in: also opens the camera for a bounded two-minute measurement test.
.\.venv\Scripts\python.exe examples/e2e.py --camera-consent
```

The E2E harness starts and stops its own localhost backend. Results are saved to
`artifacts/e2e/latest.json`; camera frames, vital values, credentials and raw SDK
logs are not saved. A failed live test is reported as failed, not replaced with
a mock success. The camera bridge also accepts `--diagnostics` and
`--duration-seconds=120` for credential-safe lifecycle diagnostics and automatic
session teardown. Without explicit consent, the E2E harness skips the camera.

Official references: [ElevenLabs TTS](https://elevenlabs.io/docs/api-reference/text-to-speech/convert),
[Scribe transcription](https://elevenlabs.io/docs/api-reference/speech-to-text/convert),
[Presage Node SDK](https://smartspectra.presagetech.com/docs/nodejs), and
[Tiger refresh policies](https://www.tigerdata.com/docs/reference/timescaledb/continuous-aggregates/add_continuous_aggregate_policy).

Snowflake remains excluded.
