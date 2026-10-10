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

REAL_CLIENT = httpx.Client


class LLMTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {"GLM_API_KEY": "test-secret"}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

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
