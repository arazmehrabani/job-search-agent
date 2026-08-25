from __future__ import annotations
from datetime import datetime, timedelta, timezone
import json
import tempfile
import unittest
from pathlib import Path

from src.config import load_config
from src.models import Job, MatchResult
from src.filters import hard_filter, freshness_bucket
from src.priority import calculate_priority
from src.relevance import title_relevance_gate
from src.sources.arbeitsagentur import ArbeitsagenturSource
from src.db import Database
from src.dashboard import build_dashboard


class V181CorrectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = load_config("config.yaml")

    def _job(self, days: int, title: str = "Mechanical Engineer") -> Job:
        return Job(
            source="arbeitsagentur", source_id=f"x{days}", title=title, company="ACME",
            location="Berlin, Berlin, DE", url=f"https://example.com/{days}",
            description="Mechanical engineering CAD machinery structural analysis",
            published_at=datetime.now(timezone.utc) - timedelta(days=days),
        )

    def test_8_to_14_days_are_fully_eligible(self):
        job = self._job(10)
        self.assertEqual(freshness_bucket(job, self.cfg), "recent")
        ok, reason = hard_filter(job, self.cfg)
        self.assertTrue(ok, reason)

    def test_15_to_30_days_survive_hard_filter_for_live_check(self):
        job = self._job(22)
        self.assertEqual(freshness_bucket(job, self.cfg), "active_grace")
        ok, reason = hard_filter(job, self.cfg)
        self.assertTrue(ok, reason)

    def test_31_to_45_days_require_strong_title(self):
        strong = self._job(35, "Structural Analysis Engineer")
        generic = self._job(35, "Systems Engineer")
        self.assertEqual(freshness_bucket(strong, self.cfg), "strong_title_grace")
        self.assertTrue(hard_filter(strong, self.cfg)[0])
        self.assertFalse(hard_filter(generic, self.cfg)[0])

    def test_location_de_not_penalized(self):
        job = self._job(1)
        m = MatchResult(score=80, recommendation="APPLY", language_fit=90, german_requirement="none", career_tier="core")
        _, _, reasons = calculate_priority(job, m, self.cfg)
        self.assertNotIn("Location may be outside preferred area", reasons)

    def test_city_only_german_location_not_penalized(self):
        job = self._job(1)
        job.location = "Hamburg"
        m = MatchResult(score=80, recommendation="APPLY", language_fit=90, german_requirement="none", career_tier="core")
        _, _, reasons = calculate_priority(job, m, self.cfg)
        self.assertNotIn("Location may be outside preferred area", reasons)

    def test_explicit_foreign_location_is_penalized(self):
        job = self._job(1)
        job.location = "Paris, France"
        m = MatchResult(score=80, recommendation="APPLY", language_fit=90, german_requirement="none", career_tier="core")
        _, _, reasons = calculate_priority(job, m, self.cfg)
        self.assertIn("Location may be outside preferred area", reasons)

    def test_ba_title_cleanup_rank_and_company(self):
        clean = ArbeitsagenturSource._clean_result_title(
            "4: Mechanical Design Engineer (m/w/d) bei Loesche GmbH", "Loesche GmbH"
        )
        self.assertEqual(clean, "Mechanical Design Engineer (m/w/d)")

    def test_frontend_product_design_is_local_reject(self):
        job = Job(
            "arbeitnow", "x", "Director of Product Design, Frontend Technologies, Marketplace Technologies",
            "Vinted", "Berlin, Germany", "https://example.com/product-design",
        )
        gate = title_relevance_gate(job, self.cfg)
        self.assertFalse(gate.keep)
        self.assertEqual(gate.reason, "SOFTWARE_PRODUCT_DESIGN")

    def test_dashboard_german_context_and_rejected_reasoning_and_run_usage(self):
        with tempfile.TemporaryDirectory() as td:
            old = Path.cwd()
            try:
                import os
                os.chdir(td)
                Path("output").mkdir()
                Path("output/discovery_report.json").write_text(json.dumps({"automatic_discovery_active": True, "raw_results": 1, "sources": []}), encoding="utf-8")
                Path("output/last_run_report.json").write_text(json.dumps({
                    "usage_this_run": {"calls": 3, "input_tokens": 1000, "output_tokens": 200},
                    "usage_by_operation_this_run": [{"operation": "job_screen", "calls": 2, "input_tokens": 500, "output_tokens": 100}],
                }), encoding="utf-8")
                db = Database("output/x.db")
                job = Job("manual", "1", "Structural Analysis Engineer", "ACME", "Hamburg, DE", "https://example.com/x")
                fp = db.upsert_job(job); db.set_active(fp, "active")
                m = MatchResult(
                    score=41, recommendation="SKIP", priority_score=49, priority_label="REJECT", source="codex_cli",
                    reasoning="Rejected because aerospace certification evidence is missing.",
                    missing_required=["Aircraft certification methods"], german_requirement="none", language_fit=55,
                    contextual_german_importance="likely_important", contextual_german_reason="German shop-floor coordination is frequent.",
                )
                db.set_match(fp, m)
                out = Path("output/dashboard.html")
                build_dashboard(db, str(out), cfg=self.cfg)
                text = out.read_text(encoding="utf-8")
                self.assertIn("AI calls this run", text)
                self.assertIn(">3<", text)
                self.assertIn("Not explicit ⚠ likely important", text)
                self.assertIn("why rejected", text)
                self.assertIn("Aircraft certification methods", text)
                db.close()
            finally:
                os.chdir(old)


if __name__ == "__main__":
    unittest.main()
