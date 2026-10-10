"""Run with python -m unittest discover -s tests -v.

Geometry checks exercise real cadgen exports when the optional runtime is installed.
No LLM or sponsor credentials are needed.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from roboforge.cad.engine import ARTIFACTS, CADBuildFailed, build, runtime_status
from roboforge.cad.spec import MechanicalRequest, PartSpec
from roboforge.cad.spec import PartProposal
from roboforge.main import app


class SpecChecks(unittest.TestCase):
    def test_bad_interfaces_and_nonfinite_numbers(self):
        for overrides in ({"hole_inset_mm": 2}, {"width_mm": 10}, {"length_mm": float("nan")},
                          {"kind": "motor_bracket", "hole_inset_mm": 8}):
            with self.subTest(overrides=overrides), self.assertRaises(ValidationError):
                PartSpec(**{"kind": "chassis_plate", **overrides})

    def test_request_requires_one_input(self):
        with self.assertRaises(ValidationError):
            MechanicalRequest()
        with self.assertRaises(ValidationError):
            MechanicalRequest(prompt="an arm", spec=PartSpec(kind="arm_link"))


class APIContract(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.project = self.client.post("/projects", json={"name": "CAD tests"}).json()
        self.endpoint = f"/projects/{self.project['id']}/agents/mechanical"

    def test_worker_failure_does_not_save_a_revision(self):
        with patch("roboforge.cad.engine.build", side_effect=CADBuildFailed("test failure")):
            response = self.client.post(self.endpoint, json={"spec": {"kind": "arm_link"}})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(self.client.get(f"/projects/{self.project['id']}").json()["revision"], 1)

    def test_foreign_design_cannot_be_downloaded(self):
        response = self.client.get(f"/projects/{self.project['id']}/cad/{'a' * 64}/step")
        self.assertEqual(response.status_code, 404)

    def test_prompt_proposal_is_validated_before_build(self):
        with patch("roboforge.agents.generate_structured", side_effect=ValueError("bad dimensions")):
            response = self.client.post(self.endpoint, json={"prompt": "arm link"})
        self.assertEqual(response.status_code, 422)


@unittest.skipUnless(runtime_status()["configured"], "Install .[cad] to verify native exports")
class CADIntegration(unittest.TestCase):
    def test_exports_cache_edits_and_revision_downloads(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {"ROBOFORGE_CAD_ROOT": directory}):
            for kind in ("arm_link", "chassis_plate", "motor_bracket"):
                with self.subTest(kind=kind):
                    spec = PartSpec(kind=kind)
                    result = build(spec)
                    self.assertTrue(all(result["geometry"]["checks"].values()))
                    for path in ARTIFACTS.values():
                        self.assertGreater((Path(directory) / result["design_id"] / path).stat().st_size, 0)
                    self.assertTrue(build(spec)["cached"])
            client = TestClient(app)
            project = client.post("/projects", json={"name": "Manufacturing demo"}).json()
            endpoint = f"/projects/{project['id']}/agents/mechanical"
            first = client.post(endpoint, json={"spec": {"kind": "arm_link"}, "estimated_unit_cost_usd": 8})
            self.assertEqual(first.status_code, 200, first.text)
            first = first.json()
            repeated = client.post(endpoint, json={"spec": {"kind": "arm_link"}, "estimated_unit_cost_usd": 8})
            self.assertEqual(repeated.status_code, 200, repeated.text)
            self.assertEqual(repeated.json()["component_id"], first["component_id"])
            self.assertTrue(repeated.json()["cached"])
            proposal = PartProposal(spec=PartSpec(kind="arm_link", length_mm=160),
                                    assumptions=["Motor interface requires verification."],
                                    explanation="Length increased; other dimensions preserved.")
            with patch("roboforge.agents.generate_structured", return_value=proposal) as model:
                second = client.post(endpoint, json={"prompt": "Make it 40 mm longer",
                                                    "base_design_id": first["design_id"]})
                self.assertIn("Base part:", model.call_args.args[1])
            self.assertEqual(second.status_code, 200, second.text)
            second = second.json()
            self.assertNotEqual(first["design_id"], second["design_id"])
            self.assertEqual(first["component_id"], second["component_id"])
            self.assertEqual(second["assumptions"], proposal.assumptions)
            latest = client.get(f"/projects/{project['id']}").json()
            self.assertEqual(len(latest["components"]), 1)
            self.assertEqual(latest["components"][0]["unit_cost_usd"], 8)
            report = client.get(first["downloads"]["report"])
            self.assertEqual(report.status_code, 200)
            self.assertEqual(json.loads(report.content)["bounds_mm"], [120, 40, 6])
            step = client.get(second["downloads"]["step"])
            self.assertEqual(step.status_code, 200)
            self.assertIn(b"ISO-10303-21", step.content)
            glb = client.get(second["downloads"]["glb"])
            self.assertEqual(glb.content[:4], b"glTF")
            before = client.get(first["downloads"]["report"].replace(f"revision={first['revision']}", "revision=1"))
            self.assertEqual(before.status_code, 404)


if __name__ == "__main__":
    unittest.main()
