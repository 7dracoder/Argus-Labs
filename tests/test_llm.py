"""Exercise provider requests and response validation without spending API credits."""
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
from fastapi.testclient import TestClient

from roboforge.cad.spec import PartProposal, PartSpec
from roboforge.llm import LLMResponseError, LLMUnavailable, generate_structured, llm_status
from roboforge.main import app
from roboforge import llm

REAL_CLIENT = httpx.Client


class LLMTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {"GLM_API_KEY": "test-secret"}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        llm._fallback_until.clear()
        self.addCleanup(llm._fallback_until.clear)

    def mock_transport(self, handler):
        return patch("httpx.Client", side_effect=lambda **kwargs: REAL_CLIENT(
            transport=httpx.MockTransport(handler), **kwargs))

    def test_default_glm_schema_and_account_endpoint(self):
        def handler(request):
            self.assertEqual(str(request.url), "https://api.z.ai/api/paas/v4/chat/completions")
            self.assertEqual(request.headers["Authorization"], "Bearer test-secret")
            body = json.loads(request.content)
            self.assertEqual(body["model"], "glm-5.3")
            self.assertEqual(body["response_format"], {"type": "json_object"})
            self.assertEqual(body["thinking"], {"type": "enabled"})
            self.assertIn("JSON Schema", body["messages"][0]["content"])
            return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
                "content": json.dumps({"spec": {"kind": "arm_link"}, "explanation": "An arm link."}),
                "reasoning_content": "This is separate and must not be parsed as JSON.",
            }}]})
        with self.mock_transport(handler):
            part = generate_structured("Robot engineer", "Arm link", PartProposal)
        self.assertEqual(part.spec.kind, "arm_link")
        self.assertNotIn("test-secret", json.dumps(llm_status()))

    def test_invalid_incomplete_and_rejected_outputs(self):
        cases = [
            (200, {"choices": []}),
            (200, {"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]}),
            (200, {"choices": [{"finish_reason": "stop", "message": {"content": "not JSON"}}]}),
            (200, {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({
                "spec": {"kind": "arm_link", "length_mm": -10}, "explanation": "invalid"})}}]}),
            (401, {"error": "test-secret vendor detail"}),
        ]
        for status, payload in cases:
            with self.subTest(status=status, payload=payload):
                with self.mock_transport(lambda request: httpx.Response(status, json=payload)):
                    with self.assertRaises(LLMResponseError) as caught:
                        generate_structured("Engineer", "Arm", PartProposal)
                    self.assertNotIn("test-secret", str(caught.exception))

    def test_glm_requires_its_key_even_when_gemini_has_one(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "gemini-key"}, clear=True):
            with self.assertRaises(LLMUnavailable):
                generate_structured("Engineer", "Arm", PartProposal)

    def test_authentication_failure_gives_safe_actionable_guidance(self):
        payload = {"error": {"code": "1000", "message": "private vendor detail test-secret"}}
        with self.mock_transport(lambda request: httpx.Response(401, json=payload)):
            with self.assertRaises(LLMResponseError) as caught:
                generate_structured("Engineer", "Arm", PartProposal)
        self.assertIn("Replace GLM_API_KEY", str(caught.exception))
        self.assertNotIn("test-secret", str(caught.exception))
        self.assertNotIn("private vendor", str(caught.exception))

    def test_auth_error_with_non_object_body_remains_sanitized(self):
        for payload in [[], {"error": "private detail"}, {"error": {"code": "1005"}}]:
            with self.subTest(payload=payload), self.mock_transport(
                lambda request: httpx.Response(401, json=payload)):
                with self.assertRaises(LLMResponseError) as caught:
                    generate_structured("Engineer", "Arm", PartProposal)
                self.assertIn("authentication", str(caught.exception))

    def test_surrounding_key_and_endpoint_whitespace_is_not_sent(self):
        def handler(request):
            self.assertEqual(request.headers["Authorization"], "Bearer test-secret")
            self.assertEqual(str(request.url), "https://api.z.ai/api/paas/v4/chat/completions")
            return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
                "content": json.dumps({"spec": {"kind": "arm_link"}, "explanation": "An arm link."})}}]})
        with patch.dict(os.environ, {"GLM_API_KEY": " test-secret ",
                                   "GLM_BASE_URL": " https://api.z.ai/api/paas/v4/ "}):
            with self.mock_transport(handler):
                self.assertEqual(generate_structured("Engineer", "Arm", PartProposal).spec.kind, "arm_link")

    def test_switch_to_gemini(self):
        proposal = PartProposal(spec=PartSpec(kind="arm_link"), explanation="Arm link")
        client = Mock()
        client.models.generate_content.return_value = SimpleNamespace(parsed=proposal)
        with patch.dict(os.environ, {"LLM_PROVIDER": "gemini", "GEMINI_API_KEY": "gemini-key",
                                    "GEMINI_MODEL": "future-model"}, clear=True):
            with patch("roboforge.llm._gemini_client", return_value=client):
                self.assertEqual(generate_structured("Engineer", "Arm", PartProposal), proposal)
                self.assertEqual(client.models.generate_content.call_args.kwargs["model"], "future-model")
                config = client.models.generate_content.call_args.kwargs["config"]
                self.assertEqual(config.response_json_schema, PartProposal.model_json_schema())
                self.assertIsNone(config.response_schema)
                self.assertFalse(config.response_json_schema["$defs"]["PartSpec"]["additionalProperties"])

    def test_gemini_quota_uses_baseten_then_retries_primary_after_cooldown(self):
        from google.genai.errors import ClientError
        proposal = PartProposal(spec=PartSpec(kind="arm_link"), explanation="Arm link")
        client = Mock()
        client.models.generate_content.side_effect = [
            ClientError(429, {"error": {"status": "RESOURCE_EXHAUSTED", "message": "gemini-key private"}}),
            SimpleNamespace(parsed=proposal),
        ]
        clock = [100.0]
        def handler(request):
            self.assertEqual(str(request.url), "https://inference.baseten.co/v1/chat/completions")
            self.assertEqual(request.headers["Authorization"], "Bearer baseten-secret")
            self.assertEqual(json.loads(request.content)["model"], "zai-org/GLM-5.3")
            return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
                "content": proposal.model_dump_json()}}]})
        with patch.dict(os.environ, {"LLM_PROVIDER": "gemini", "GEMINI_API_KEY": "gemini-key",
                                    "LLM_FALLBACK_PROVIDER": "baseten", "BASETEN_API_KEY": "baseten-secret"}, clear=True), \
                patch("roboforge.llm._gemini_client", return_value=client), \
                patch("roboforge.llm.monotonic", side_effect=lambda: clock[0]), self.mock_transport(handler):
            self.assertEqual(generate_structured("Engineer", "Arm", PartProposal), proposal)
            state = llm_status()
            self.assertEqual(state["active_provider"], "baseten")
            self.assertEqual(state["primary_retry_after_seconds"], 60)
            self.assertNotIn("gemini-key", json.dumps(state))
            self.assertNotIn("baseten-secret", json.dumps(state))
            self.assertEqual(generate_structured("Engineer", "Arm", PartProposal), proposal)
            self.assertEqual(client.models.generate_content.call_count, 1)
            self.assertEqual(os.environ["LLM_PROVIDER"], "gemini")
            clock[0] += 61
            self.assertEqual(generate_structured("Engineer", "Arm", PartProposal), proposal)
            self.assertEqual(client.models.generate_content.call_count, 2)
            self.assertEqual(llm_status()["active_provider"], "gemini")

    def test_gemini_errors_other_than_quota_do_not_use_backup(self):
        from google.genai.errors import APIError
        for code in (400, 401, 403, 404, 500, 503):
            client = Mock()
            client.models.generate_content.side_effect = APIError(code, {"error": {"message": "gemini-key private"}})
            with self.subTest(code=code), patch.dict(os.environ, {
                "LLM_PROVIDER": "gemini", "GEMINI_API_KEY": "gemini-key",
                "LLM_FALLBACK_PROVIDER": "baseten", "GLM_API_KEY": "baseten-secret"}, clear=True), \
                    patch("roboforge.llm._gemini_client", return_value=client), \
                    patch("roboforge.llm._generate_glm") as backup:
                with self.assertRaises(LLMResponseError) as caught:
                    generate_structured("Engineer", "Arm", PartProposal)
                self.assertNotIn("gemini-key", str(caught.exception))
                self.assertNotIn("private", str(caught.exception))
                backup.assert_not_called()

    def test_gemini_invalid_output_does_not_use_backup(self):
        client = Mock()
        client.models.generate_content.return_value = SimpleNamespace(parsed=None, text='{"private":"gemini-key"}')
        with patch.dict(os.environ, {"LLM_PROVIDER": "gemini", "GEMINI_API_KEY": "gemini-key",
                                    "LLM_FALLBACK_PROVIDER": "baseten", "GLM_API_KEY": "backup-key"}), \
                patch("roboforge.llm._gemini_client", return_value=client), \
                patch("roboforge.llm._generate_glm") as backup:
            with self.assertRaisesRegex(LLMResponseError, "invalid structured output"):
                generate_structured("Engineer", "Arm", PartProposal)
            backup.assert_not_called()

    def test_gemini_quota_without_backup_is_safe(self):
        from google.genai.errors import ClientError
        client = Mock()
        client.models.generate_content.side_effect = ClientError(429, {"error": {"message": "gemini-key private"}})
        for fallback in ("", "baseten"):
            with self.subTest(fallback=fallback), patch.dict(os.environ, {
                "LLM_PROVIDER": "gemini", "GEMINI_API_KEY": "gemini-key", "LLM_FALLBACK_PROVIDER": fallback
            }, clear=True), patch("roboforge.llm._gemini_client", return_value=client), \
                    patch("roboforge.llm._generate_glm") as backup:
                with self.assertRaisesRegex(LLMResponseError, "quota or rate limit"):
                    generate_structured("Engineer", "Arm", PartProposal)
                backup.assert_not_called()

    def test_invalid_backup_configuration_is_not_silently_used(self):
        for settings in ({"LLM_FALLBACK_PROVIDER": "gemini"},
                         {"LLM_FALLBACK_PROVIDER": "baseten", "LLM_FALLBACK_COOLDOWN_SECONDS": "zero"}):
            with self.subTest(settings=settings), patch.dict(os.environ, {
                "LLM_PROVIDER": "gemini", "GEMINI_API_KEY": "gemini-key", **settings
            }, clear=True), patch("roboforge.llm._gemini_client") as client:
                with self.assertRaises(LLMUnavailable):
                    generate_structured("Engineer", "Arm", PartProposal)
                client.assert_not_called()

    def test_backup_failure_is_not_reported_as_success(self):
        from google.genai.errors import ClientError
        client = Mock()
        client.models.generate_content.side_effect = ClientError(429, {})
        with patch.dict(os.environ, {"LLM_PROVIDER": "gemini", "GEMINI_API_KEY": "gemini-key",
                                    "LLM_FALLBACK_PROVIDER": "baseten", "GLM_API_KEY": "backup-key"}), \
                patch("roboforge.llm._gemini_client", return_value=client), \
                self.mock_transport(lambda request: httpx.Response(401, json={"error": "backup-key"})):
            with self.assertRaisesRegex(LLMResponseError, "Baseten authentication failed") as caught:
                generate_structured("Engineer", "Arm", PartProposal)
            self.assertNotIn("backup-key", str(caught.exception))

    def test_baseten_defaults_and_provider_key_precedence(self):
        def handler(request):
            self.assertEqual(str(request.url), "https://inference.baseten.co/v1/chat/completions")
            self.assertEqual(request.headers['Authorization'], 'Bearer baseten-secret')
            body = json.loads(request.content)
            self.assertEqual(body['model'], 'zai-org/GLM-5.3')
            self.assertEqual(body['reasoning_effort'], 'low')
            self.assertEqual(body['response_format'], {'type': 'json_object'})
            self.assertNotIn('thinking', body)
            return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {
                'content': json.dumps({'spec': {'kind': 'arm_link'}, 'explanation': 'An arm link.'})}}]})
        with patch.dict(os.environ, {'LLM_PROVIDER': 'baseten', 'BASETEN_API_KEY': 'baseten-secret',
                                    'GLM_API_KEY': 'other-secret'}, clear=True):
            with self.mock_transport(handler):
                self.assertEqual(generate_structured('Engineer', 'Arm', PartProposal).spec.kind, 'arm_link')
            self.assertEqual(llm_status(), {'provider': 'baseten', 'model': 'zai-org/GLM-5.3', 'configured': True})

    def test_baseten_supports_existing_glm_key_but_not_zai_key(self):
        with patch.dict(os.environ, {'LLM_PROVIDER': 'baseten', 'ZAI_API_KEY': 'zai-secret'}, clear=True):
            self.assertFalse(llm_status()['configured'])
            with self.assertRaises(LLMUnavailable):
                generate_structured('Engineer', 'Arm', PartProposal)
        with patch.dict(os.environ, {'LLM_PROVIDER': 'baseten', 'GLM_API_KEY': 'test-secret'}, clear=True):
            with self.mock_transport(lambda request: httpx.Response(401, json={'error': 'test-secret'})):
                with self.assertRaises(LLMResponseError) as caught:
                    generate_structured('Engineer', 'Arm', PartProposal)
            self.assertIn('Baseten authentication failed', str(caught.exception))
            self.assertNotIn('test-secret', str(caught.exception))


if __name__ == "__main__":
    unittest.main()
