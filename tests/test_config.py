import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from roboforge.config import ENV_FILE, load_environment


class EnvironmentTests(unittest.TestCase):
    def test_default_is_project_root(self):
        self.assertEqual(ENV_FILE, Path(__file__).resolve().parent.parent / ".env")

    def test_loads_values_preserves_shell_and_literal_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("GLM_API_KEY=test-${TOKEN}\nLLM_PROVIDER=glm\n"
                            "ELEVENLABS_API_KEY=\n", encoding="utf-8")
            with patch.dict(os.environ, {"LLM_PROVIDER": "gemini", "TOKEN": "expanded"}, clear=True):
                self.assertTrue(load_environment(path))
                self.assertEqual(os.environ["GLM_API_KEY"], "test-${TOKEN}")
                self.assertEqual(os.environ["LLM_PROVIDER"], "gemini")
                self.assertEqual(os.environ["ELEVENLABS_API_KEY"], "")

    def test_missing_file_is_optional(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertFalse(load_environment(Path(directory) / "missing.env"))


if __name__ == "__main__":
    unittest.main()
