"""Explicit, small live sponsor checks. Does not capture the mic or camera."""
import argparse
import base64
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from roboforge.integrations.elevenlabs import elevenlabs, ElevenLabsUnavailable
from roboforge.integrations.tiger import tiger, TelemetryEvent, TigerUnavailable
from roboforge.llm import LLMUnavailable, LLMResponseError
from roboforge.models import RobotProject
from roboforge.voice import VoiceRequest, respond


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tiger", action="store_true", help="Write two labelled development telemetry samples")
    parser.add_argument("--voice", action="store_true", help="One GLM reply, ElevenLabs speech, and Scribe transcription (uses credits)")
    args = parser.parse_args()
    success = True
    if args.tiger:
        project_id = "setup-smoke-" + uuid4().hex[:8]
        try:
            for value in [10, 20]:
                tiger.record(project_id, TelemetryEvent(metric="battery_pct", value=value,
                                                       unit="percent", scenario_id="integration-smoke"))
            summary = tiger.summary(project_id)
            points = tiger.timeseries(project_id, datetime.now(timezone.utc)-timedelta(hours=1))
            assert summary["metrics"][0]["average"] == 15
            assert summary["metrics"][0]["samples"] == 2
            assert points["points"][0]["average"] == 15
            print(json.dumps({"tiger": "passed", "schema": tiger.health(),
                              "smoke_project": project_id, "samples": 2, "minute_rollup": "passed"}))
        except (TigerUnavailable, AssertionError, IndexError) as error:
            print(json.dumps({"tiger": "failed", "error": str(error)}))
            success = False
    if args.voice:
        try:
            result = respond(RobotProject(name="Voice smoke test"),
                             VoiceRequest(message="Introduce yourself in one short sentence. Do not propose CAD."), {})
            if result["audio"] is None:
                raise ElevenLabsUnavailable(result["speech_error"] or "No speech")
            audio = base64.b64decode(result["audio"]["base64"])
            output = Path("artifacts/voice/forge-intro.mp3")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(audio)
            transcript = elevenlabs.transcribe(audio, "audio/mpeg")
            print(json.dumps({"voice": "passed", "reply": result["reply"],
                              "transcription": transcript["text"], "audio_path": str(output.resolve())}))
        except (LLMUnavailable, LLMResponseError, ElevenLabsUnavailable) as error:
            print(json.dumps({"voice": "failed", "error": str(error)}))
            success = False
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
