import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from pydantic import ValidationError

from roboforge.finance import TCOInput, build_bom, estimate_tco
from roboforge.finance.research import (AnalystNote, ResearchInput, annual_revenue, company_data,
                                       evaluate, research_report, snapshot, _cache)
from roboforge.llm import LLMUnavailable
from roboforge.main import app
from roboforge.models import RobotProject


class FinancialResearchTests(unittest.TestCase):
    def setUp(self):
        _cache.clear()

    def test_sec_annual_periods_are_not_quarters_or_comparative_fiscal_labels(self):
        def observation(start, end, filed, value, **kw):
            return {"start": start, "end": end, "filed": filed, "val": value,
                    "accn": "0000097210-23-000001", "form": "10-K", "fy": 2023, **kw}
        records = [observation("2021-01-01", "2021-12-31", "2022-02-01", 100),
                   observation("2021-01-01", "2021-12-31", "2023-02-01", 99),
                   observation("2022-01-01", "2022-12-31", "2023-02-01", 120),
                   observation("2022-10-01", "2022-12-31", "2023-02-01", 30),
                   observation("2022-01-01", "2022-12-31", "2023-02-01", float("inf")),
                   observation("2022-01-01", "2022-12-31", "2023-02-01", 121, accn="bad")]
        data = {"cik": 97210, "facts": {"us-gaap": {"Revenues": {"units": {"USD": records}}}}}
        result = annual_revenue(data, "0000097210")
        self.assertEqual([r["revenue_usd"] for r in result], [100, 120])
        self.assertTrue(result[0]["url"].startswith("https://www.sec.gov/Archives/"))
        with self.assertRaises(ValueError):
            annual_revenue(data, "0001045810")

    def test_walk_forward_actual_never_enters_forecast_and_baseline_can_win(self):
        records = [{"period_end": f"{year}-12-31", "filed": f"{year+1}-02-01", "revenue_usd": value}
                   for year, value in zip(range(2020, 2024), [100, 120, 80, 130])]
        report = evaluate(records)
        self.assertEqual(report["samples"], 2)
        self.assertEqual([f["trend_usd"] for f in report["folds"]], [140, 40])
        self.assertEqual(report["trend_mae_usd"], 75)
        self.assertEqual(report["baseline_mae_usd"], 45)
        records[-1]["revenue_usd"] = 500
        self.assertEqual(evaluate(records)["folds"][-1]["trend_usd"], 40)
        records[-1]["filed"] = records[-2]["filed"]
        self.assertEqual(evaluate(records)["samples"], 1)

    def test_snapshot_is_labeled_and_reports_all_historical_folds(self):
        report = research_report(RobotProject(name="Research"), ResearchInput(use_ai=False))
        self.assertEqual(report["source_mode"], "snapshot")
        self.assertEqual(report["companies"][0]["evaluation"]["samples"], 3)
        self.assertFalse(report["companies"][0]["evaluation"]["point_in_time"])
        self.assertEqual(report["companies"][0]["revenue_growth_pct"], 5.36)
        self.assertEqual(report["companies"][1]["revenue_growth_pct"], 114.2)
        self.assertEqual(len(report["sources"]), 10)
        self.assertEqual(len(report["economics"]), 3)
        self.assertIsNone(report["economics"][0]["roi_pct"])
        self.assertNotIn("\u2014", str(report))

    def test_live_failure_never_silently_becomes_snapshot_or_leaks_response(self):
        with patch("roboforge.finance.research.httpx.get", return_value=httpx.Response(
                403, text="secret vendor body", request=httpx.Request("GET", "https://data.sec.gov"))):
            data = company_data("TER", "live")
        self.assertEqual(data["status"], "unavailable")
        self.assertEqual(data["records"], [])
        self.assertNotIn("secret vendor body", str(data))

    def test_ai_citations_are_validated_and_provider_failure_keeps_calculations(self):
        project = RobotProject(name="Research")
        for generated in (LLMUnavailable("offline"), AnalystNote(findings=[{
                "observation": "Unverified assertion", "source_ids": ["invented"]}],
                questions_to_check=["Question"])):
            kw = {"side_effect": generated} if isinstance(generated, Exception) else {"return_value": generated}
            with patch("roboforge.finance.research.generate_structured", **kw):
                report = research_report(project, ResearchInput())
            self.assertEqual(report["ai_status"], "unavailable")
            self.assertEqual(len(report["economics"]), 3)
            self.assertNotIn("Unverified assertion", str(report))
        valid = AnalystNote(findings=[{"observation": "Review demand\u2014check segmentation.", "source_ids": ["TER-4"]}], questions_to_check=["Why?"])
        with patch("roboforge.finance.research.generate_structured", return_value=valid):
            report = research_report(project, ResearchInput())
        self.assertEqual(report["ai_status"], "generated")
        self.assertNotIn("\u2014", str(report))

    def test_api_revision_is_stable_invalid_source_and_numbers_are_rejected(self):
        client = TestClient(app)
        project = client.post("/projects/demo").json()
        path = f"/projects/{project['id']}/finance/research"
        result = client.post(path, params={"revision": project["revision"]}, json={"use_ai": False})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["revision"], project["revision"])
        self.assertEqual(client.get(f"/projects/{project['id']}").json()["revision"], project["revision"])
        self.assertEqual(client.post(path, json={"source": "private"}).status_code, 422)
        self.assertEqual(client.post(path, json={"economics": {"hours_per_day": 25}}).status_code, 422)
        self.assertEqual(client.post("/projects/missing/finance/research", json={"use_ai": False}).status_code, 404)
        with self.assertRaises(ValidationError):
            TCOInput(annual_savings_usd=float("inf"))

    def test_zero_savings_has_negative_roi_and_empty_bom_has_no_roi(self):
        project = TestClient(app).post("/projects/demo").json()
        model = RobotProject.model_validate(project)
        result = estimate_tco(model.components, build_bom(model.components), TCOInput(annual_savings_usd=0))
        self.assertEqual(result.roi_pct, -100)
        self.assertIsNone(result.payback_years)
        empty = estimate_tco([], build_bom([]), TCOInput(annual_savings_usd=1500))
        self.assertIsNone(empty.roi_pct)


if __name__ == "__main__":
    unittest.main()
