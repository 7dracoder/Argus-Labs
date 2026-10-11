import base64
import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import httpx
try:
    import psycopg
except ImportError:
    psycopg = None
from fastapi.testclient import TestClient
from pydantic import ValidationError

from roboforge.cad.spec import PartProposal, PartSpec
from roboforge.integrations.elevenlabs import ElevenLabsClient, ElevenLabsUnavailable
from roboforge.integrations.presage import PresageInteractionSignal, recommended_interface
from roboforge.integrations.tiger import TelemetryEvent, TigerTelemetry, TigerUnavailable
from roboforge.main import app
from roboforge.models import RobotProject
from roboforge.store import store
from roboforge.voice import VoiceReply, VoiceRequest, respond

REAL_CLIENT = httpx.Client


class TigerTests(unittest.TestCase):
    def setUp(self):
        with patch.dict(os.environ, {}, clear=True):
            self.database = TigerTelemetry()
        if psycopg:
            self.resolver = patch("psycopg.conninfo.conninfo_attempts", side_effect=lambda settings: [
                {**settings, "hostaddr": "203.0.113.10"}])
            self.resolver.start()
            self.addCleanup(self.resolver.stop)

    def test_memory_is_not_reported_as_connected_and_groups_are_isolated(self):
        self.assertFalse(self.database.health()["connected"])
        for value in [4, 8]:
            self.database.record("a", TelemetryEvent(metric="torque_nm", value=value, unit="Nm"))
        self.database.record("b", TelemetryEvent(metric="torque_nm", value=999, unit="Nm"))
        summary = self.database.summary("a")
        self.assertEqual(summary["metrics"][0]["average"], 6)
        self.assertEqual(summary["metrics"][0]["samples"], 2)

    def test_nonfinite_and_naive_timestamp_rejected(self):
        for value in [float("nan"), float("inf")]:
            with self.assertRaises(ValidationError):
                TelemetryEvent(metric="x", value=value)
        with self.assertRaises(ValidationError):
            TelemetryEvent(metric="x", value=1, observed_at=datetime(2026, 1, 1))

    def test_minute_points_filter_and_limit(self):
        start = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)
        for seconds, value in [(1, 10), (30, 20), (65, 30)]:
            self.database.record("a", TelemetryEvent(observed_at=start+timedelta(seconds=seconds),
                                                    scenario_id="run", metric="battery", value=value))
        points = self.database.timeseries("a", start, "run", 10)["points"]
        self.assertEqual(len(points), 2)
        self.assertEqual(points[0]["average"], 15)
        self.assertEqual(points[0]["samples"], 2)
        self.assertEqual(self.database.timeseries("a", start, "other")["points"], [])
        self.assertEqual(self.database.timeseries("a", start, limit=1)["points"][0]["average"], 30)

    @unittest.skipUnless(psycopg, "Optional Tiger driver is not installed")
    def test_remote_requires_ssl_and_driver_errors_are_sanitized(self):
        self.database.database_url = "postgresql://user:secret@db.example.com/db?sslmode=disable"
        with patch("psycopg.connect") as connect:
            with self.assertRaises(TigerUnavailable):
                self.database.initialize()
            connect.assert_not_called()
        self.database.database_url = "postgresql://user:secret@db.example.com/db"
        with patch("psycopg.connect", side_effect=psycopg.OperationalError("password=secret")) as connect:
            with self.assertRaises(TigerUnavailable) as caught:
                self.database.initialize()
            self.assertNotIn("secret", str(caught.exception))
            self.assertEqual(connect.call_args.kwargs["sslmode"], "require")
            self.assertEqual(connect.call_args.kwargs["connect_timeout"], 2)
            self.assertEqual(connect.call_args.kwargs["host"], "db.example.com")

    @unittest.skipUnless(psycopg, "Optional Tiger driver is not installed")
    def test_multi_address_budget_backoff_and_explicit_retry(self):
        self.database.database_url = "postgresql://user:secret@db.example.com/db"
        clock = [1000.0]
        attempts = [{"host": "db.example.com", "hostaddr": f"203.0.113.{n}",
                     "sslmode": "require"} for n in range(10, 16)]
        def failed_connection(**settings):
            clock[0] += 2
            raise psycopg.errors.ConnectionTimeout("password=secret timeout expired")
        with patch("psycopg.conninfo.conninfo_attempts", return_value=attempts), \
             patch("roboforge.integrations.tiger.monotonic", side_effect=lambda: clock[0]), \
             patch("psycopg.connect", side_effect=failed_connection) as connect:
            status = self.database.health()
            self.assertEqual(status["error_code"], "connection_timeout")
            self.assertEqual(connect.call_count, 4)
            self.assertEqual(clock[0], 1008)
            self.assertNotIn("secret", json.dumps(status))
            self.assertNotIn("db.example.com", json.dumps(status))
            self.assertGreater(status["retry_after_seconds"], 0)
            self.database.health()
            self.assertEqual(connect.call_count, 4, "backoff prevents repeated connection storms")
            self.database.health(retry=True)
            self.assertEqual(connect.call_count, 8)
            self.assertNotEqual(connect.call_args_list[0].kwargs["hostaddr"], connect.call_args_list[4].kwargs["hostaddr"])
            self.assertTrue(all(c.kwargs["sslmode"] == "require" for c in connect.call_args_list))

    @unittest.skipUnless(psycopg, "Optional Tiger driver is not installed")
    def test_authentication_and_schema_failures_are_distinguished_without_fallback(self):
        self.database.database_url = "postgresql://user:secret@db.example.com/db"
        with patch("psycopg.connect", side_effect=psycopg.errors.InvalidPassword("secret")) as connect:
            status = self.database.health()
            self.assertEqual(status["error_code"], "authentication_failed")
            self.assertFalse(status["connected"])
            self.assertNotIn("secret", json.dumps(status))
            connect.assert_called_once()
            with self.assertRaises(TigerUnavailable):
                self.database.record("test", TelemetryEvent(metric="x", value=1))
            self.assertEqual(self.database._events, {}, "configured failures never become fake memory writes")
        self.database._retry_at = 0
        connection = MagicMock()
        connection.__enter__.return_value = connection
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.execute.side_effect = psycopg.errors.UndefinedTable("private details")
        with patch("psycopg.connect", return_value=connection):
            with self.assertRaises(TigerUnavailable) as caught:
                self.database.summary("test")
            self.assertEqual(caught.exception.code, "schema_missing")
            self.assertNotIn("private details", str(caught.exception))

    @unittest.skipUnless(psycopg, "Optional Tiger driver is not installed")
    def test_health_reports_schema_action_after_successful_connection(self):
        self.database.database_url = "postgresql://user:secret@db.example.com/db"
        connection = MagicMock()
        connection.__enter__.return_value = connection
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.side_effect = [("2.30.2",), (None, None)]
        with patch("psycopg.connect", return_value=connection):
            health = self.database.health()
        self.assertTrue(health["connected"])
        self.assertFalse(health["schema_ready"])
        self.assertIn("Initialize", health["action"])

    @unittest.skipUnless(psycopg, "Optional Tiger driver is not installed")
    def test_setup_is_idempotent_and_schedules_real_time_rollups(self):
        self.database.database_url = "postgresql://user:secret@db.example.com/db"
        connection = MagicMock()
        connection.__enter__.return_value = connection
        cursor = connection.cursor.return_value.__enter__.return_value
        with patch("psycopg.connect", return_value=connection):
            self.database.initialize()
            self.database.initialize()
        sql = "\n".join(call.args[0] for call in cursor.execute.call_args_list)
        self.assertEqual(sql.count("CREATE TABLE IF NOT EXISTS"), 2)
        self.assertIn("materialized_only = false", sql)
        self.assertIn("add_continuous_aggregate_policy", sql)
        self.assertIn("schedule_interval => INTERVAL '1 minute'", sql)


class SpeechTests(unittest.TestCase):
    def setUp(self):
        with patch.dict(os.environ, {"ELEVENLABS_API_KEY": "test-secret", "ELEVENLABS_VOICE_ID": "river"}, clear=True):
            self.speech = ElevenLabsClient()

    def transport(self, handler):
        return patch("httpx.Client", side_effect=lambda **kwargs: REAL_CLIENT(
            transport=httpx.MockTransport(handler), **kwargs))

    def test_tts_pacing_and_transcription_contract(self):
        def handler(request):
            self.assertEqual(request.headers["xi-api-key"], "test-secret")
            if "text-to-speech" in request.url.path:
                body = json.loads(request.content)
                self.assertEqual(body["voice_settings"]["speed"], 0.85)
                self.assertEqual(body["model_id"], "eleven_flash_v2_5")
                return httpx.Response(200, content=b"audio", headers={"content-type": "audio/mpeg"})
            self.assertIn(b"scribe_v2", request.content)
            self.assertIn(b"recording", request.content)
            return httpx.Response(200, json={"text": "Explain the budget", "language_code": "en"})
        with self.transport(handler):
            self.assertEqual(self.speech.synthesize("Budget", speed=0.85), b"audio")
            self.assertEqual(self.speech.transcribe(b"recording", "audio/wav")["text"], "Explain the budget")

    def test_vendor_errors_redirects_invalid_audio_and_transcripts(self):
        for status, payload in [(401, {"key": "test-secret"}), (302, {}), (200, {"text": ""}), (200, [])]:
            with self.subTest(status=status, payload=payload), self.transport(
                lambda request: httpx.Response(status, json=payload)):
                with self.assertRaises(ElevenLabsUnavailable) as caught:
                    self.speech.transcribe(b"wav", "audio/wav")
                self.assertNotIn("test-secret", str(caught.exception))
        with self.transport(lambda request: httpx.Response(200, json={"bad": "audio"})):
            with self.assertRaises(ElevenLabsUnavailable):
                self.speech.synthesize("hello")
        with self.assertRaises(ElevenLabsUnavailable):
            self.speech.synthesize("hello", "../../other-service")


class VoiceTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.project = store.create(RobotProject(name="Voice test"))
        self.telemetry = patch("roboforge.api.tiger.summary", return_value={"storage": "memory", "metrics": []})
        self.telemetry.start()
        self.addCleanup(self.telemetry.stop)

    def test_proposal_does_not_edit_design_and_pacing_controls_tts(self):
        proposal = PartProposal(spec=PartSpec(kind="arm_link"), explanation="Proposed arm")
        with patch("roboforge.voice.generate_structured", return_value=VoiceReply(reply="Confirm the dimensions?", cad_proposal=proposal)) as model:
            with patch("roboforge.voice.elevenlabs.synthesize", return_value=b"mp3") as speech:
                response = self.client.post(f"/projects/{self.project.id}/voice/agent", json={
                    "message": "Design an arm link", "interaction": {
                        "consent": True, "state": "needs_guidance", "confidence": 0.9}})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        body = response.json()
        self.assertTrue(body["requires_confirmation"])
        self.assertFalse(body["project_changed"])
        self.assertEqual(base64.b64decode(body["audio"]["base64"]), b"mp3")
        speech.assert_called_once_with("Confirm the dimensions?", speed=0.85)
        self.assertIn("BOM:", model.call_args.args[1])
        self.assertEqual(store.get(self.project.id).revision, 1)

    def test_voice_text_survives_speech_failure(self):
        with patch("roboforge.voice.generate_structured", return_value=VoiceReply(reply="Your budget is an estimate.")):
            with patch("roboforge.voice.elevenlabs.synthesize", side_effect=ElevenLabsUnavailable("No credits")):
                result = respond(self.project, VoiceRequest(message="budget?"), {})
        self.assertEqual(result["reply"], "Your budget is an estimate.")
        self.assertIsNone(result["audio"])
        self.assertEqual(result["speech_error"], "No credits")

    def test_audio_requires_consent_known_project_supported_type_and_size(self):
        with patch("roboforge.api.elevenlabs.transcribe") as transcript:
            self.assertEqual(self.client.post("/voice/transcribe", content=b"wav", headers={"content-type": "audio/wav"}).status_code, 422)
            self.assertEqual(self.client.post("/voice/transcribe?consent=true", content=b"wav", headers={"content-type": "text/plain"}).status_code, 415)
            self.assertEqual(self.client.post("/voice/transcribe?consent=true", content=b"", headers={"content-type": "audio/wav"}).status_code, 422)
            self.assertEqual(self.client.post("/voice/transcribe?consent=true", content=b"x"*(10*1024*1024+1), headers={"content-type": "audio/wav"}).status_code, 413)
            self.assertEqual(self.client.post("/projects/missing/voice/agent/audio?consent=true", content=b"wav", headers={"content-type": "audio/wav"}).status_code, 404)
            transcript.assert_not_called()

    def test_audio_to_agent_and_low_confidence_fallback(self):
        with patch("roboforge.api.elevenlabs.transcribe", return_value={"text": "What is the budget?"}):
            with patch("roboforge.voice.generate_structured", return_value=VoiceReply(reply="There is no budget yet.")):
                with patch("roboforge.voice.elevenlabs.synthesize", return_value=b"mp3"):
                    response = self.client.post(f"/projects/{self.project.id}/voice/agent/audio?consent=true", content=b"wav", headers={"content-type": "audio/wav"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["transcript"], "What is the budget?")
        signal = PresageInteractionSignal(consent=True, state="needs_guidance", confidence=0.1)
        self.assertEqual(recommended_interface(signal)["voice_speed"], 1)
        with self.assertRaises(ValueError):
            recommended_interface(PresageInteractionSignal(consent=False, state="focused", confidence=1))


if __name__ == "__main__":
    unittest.main()
