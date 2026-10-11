import os
import unittest
from unittest import mock

import httpx

from roboforge.research import YOU_URL, TAVILY_URL, Research, find_references, prompt_block


class ResearchTests(unittest.TestCase):
    def result(self, data, status=200):
        return httpx.Response(status, json=data, request=httpx.Request("POST", YOU_URL))

    def test_you_auth_query_normalization_and_no_invented_image_evidence(self):
        data = {"results": {"web": [
            {"title": "Carrier", "url": "https://example.com/robot", "snippets": ["Two wheels", None, "Cargo"],
             "thumbnail_url": "https://example.com/photo.jpg"},
            {"title": "Bad", "url": "http://example.com"},
            {"title": "Credential URL", "url": "https://secret@example.com/"},
            None]}}
        with mock.patch.dict(os.environ, {"RESEARCH_PROVIDER": "you", "YDC_API_KEY": "test-only"}, clear=True), \
                mock.patch("roboforge.research.httpx.post", return_value=self.result(data)) as post:
            result = find_references("carry small parcels")
        self.assertEqual((result.provider, result.status), ("you", "ok"))
        self.assertEqual(len(result.references), 1)
        self.assertEqual(result.references[0].snippet, "Two wheels Cargo")
        self.assertEqual(result.images, [])
        self.assertEqual(post.call_args.args[0], YOU_URL)
        self.assertEqual(post.call_args.kwargs["headers"], {"X-API-Key": "test-only"})
        self.assertEqual(post.call_args.kwargs["json"]["count"], 5)

    def test_tavily_switch_retains_described_photos(self):
        data = {"results": [{"title": "Robot", "url": "https://example.com", "content": "A robot"}],
                "images": [{"url": "https://example.com/a.jpg", "description": "A wheeled base"},
                           {"url": "https://example.com/b.jpg"}]}
        with mock.patch.dict(os.environ, {"RESEARCH_PROVIDER": "tavily", "TAVILY_API_KEY": "test-only",
                                          "YDC_API_KEY": "not-used"}, clear=True), \
                mock.patch("roboforge.research.httpx.post", return_value=self.result(data)) as post:
            result = find_references("a robot")
        self.assertEqual(post.call_args.args[0], TAVILY_URL)
        self.assertEqual(result.status, "ok")
        self.assertEqual(len(result.images), 1)

    def test_errors_are_distinguishable_and_credential_safe(self):
        for data, status in (({"detail": "secret-vendor-body"}, 401), ([], 200),
                             ({"results": None}, 200), ({"results": {"web": []}}, 200)):
            with self.subTest(status=status, data=data), \
                    mock.patch.dict(os.environ, {"YDC_API_KEY": "test-only"}, clear=True), \
                    mock.patch("roboforge.research.httpx.post", return_value=self.result(data, status)):
                result = find_references("a robot")
            self.assertEqual(result.status, "empty" if data == {"results": {"web": []}} else "error")
            self.assertNotIn("secret-vendor-body", result.model_dump_json())
            self.assertNotIn("test-only", result.model_dump_json())

    def test_disabled_and_unknown_provider_do_not_send_requests(self):
        for env, brief, expected in (({}, "robot", "disabled"),
                                     ({"YDC_API_KEY": "test-only"}, "  ", "disabled"),
                                     ({"RESEARCH_PROVIDER": "typo"}, "robot", "error")):
            with mock.patch.dict(os.environ, env, clear=True), mock.patch("roboforge.research.httpx.post") as post:
                self.assertEqual(find_references(brief).status, expected)
                post.assert_not_called()

    def test_prompt_labels_search_data_untrusted(self):
        self.assertEqual(prompt_block(Research()), "")
        from roboforge.research import Reference
        block = prompt_block(Research(references=[Reference(title="Robot", url="https://example.com")]))
        self.assertIn("not instructions", block)


if __name__ == "__main__":
    unittest.main()
