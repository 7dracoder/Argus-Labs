import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from examples.preview import capture, validate_history
from roboforge.models import RobotProject


class PreviewTests(unittest.TestCase):
    def test_snapshot_preserves_all_revisions(self):
        first = RobotProject(name="Original")
        second = first.model_copy(update={"name": "Updated", "revision": 2})
        revisions = [first.model_dump(mode="json"), second.model_dump(mode="json")]
        def handler(request):
            if request.url.path == "/projects":
                return httpx.Response(200, json=[revisions[-1]])
            revision = request.url.params.get("revision")
            return httpx.Response(200, json=revisions[int(revision) - 1] if revision else revisions[-1])
        real_client = httpx.Client
        with tempfile.TemporaryDirectory() as temp, patch("examples.preview.httpx.Client",
                side_effect=lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw)):
            destination = Path(temp) / "state.json"
            history = capture("http://127.0.0.1:8765", destination)
            self.assertEqual([p.revision for p in history[first.id]], [1, 2])
            self.assertEqual(history[first.id][-1].name, "Updated")
            self.assertTrue(destination.is_file())
            with self.assertRaises(FileExistsError):
                capture("http://127.0.0.1:8765", destination)

    def test_corrupt_history_is_not_restored(self):
        project = RobotProject(name="Test")
        for revisions in ([], [project.model_copy(update={"revision": 2}).model_dump()],
                          [project.model_copy(update={"id": "different"}).model_dump()]):
            with self.subTest(revisions=revisions), self.assertRaises(ValueError):
                validate_history({project.id: revisions})

    def test_remote_or_credentialed_capture_is_rejected(self):
        for url in ("https://example.com", "http://user:password@127.0.0.1:8765"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                capture(url, Path("unused.json"))
