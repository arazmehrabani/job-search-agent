from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from src.config import load_config
from src.db import Database
from src.models import Job, MatchResult
from src.pipeline import run_pipeline
from src.relevance import title_relevance_gate
from src.pagecheck import _clean_ba_title
from src.documents import _package_layout

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class _FakeSource:
    name = "fake"
    category = "broad"

    def __init__(self, jobs):
        self.jobs = jobs

    def health(self):
        return {"name": self.name, "category": "broad", "automatic": True,
                "configured": True, "operational": True, "reason": "test"}

    def search_many(self, queries, locations, limit):
        return list(self.jobs)


class _FakeAI:
    def __init__(self, cfg, usage_recorder=None):
        self.cfg = cfg
        self.enabled = True
        self.usage_recorder = usage_recorder

    def backend_name(self):
        return "codex_cli"

    @staticmethod
    def _ctx(context):
        return dict(
            job_language=context.get("job_language", "en"),
            employment_type=context.get("employment_type", "professional"),
            career_family=context.get("career_family", "mechanical_product_development"),
            career_family_label=context.get("career_family_label", "Mechanical"),
            career_tier=context.get("career_tier", "core"),
            source_cv=context.get("source_cv", "mechanical_en"),
            german_requirement=context.get("german_requirement", "none"),
            career_stage=context.get("career_stage", "professional"),
            schedule=context.get("schedule", "full_time"),
            contract=context.get("contract", "regular"),
        )

    def heuristic_match(self, job, profile, context, evidence_ids=None):
        return MatchResult(score=75, recommendation="REVIEW", source="heuristic",
                           analysis_version="1.8.2", evaluation_stage="pre",
                           evidence_ids=list(evidence_ids or []), language_fit=100, **self._ctx(context))

    def screen(self, job, profile, evidence_records, context, base_score):
        scores = {
            "Mechanical Engineer Alpha": 72,
            "Mechanical Engineer Beta": 80,
            "Mechanical Engineer Gamma": 98,
        }
        score = scores.get(job.title, 90)
        return {"screen_score": score, "decision": "PROMOTE", "reason": "test screen",
                "mandatory_gaps": [], "evidence_ids": [str(x.get("id")) for x in evidence_records[:4] if x.get("id")]}

    def screen_to_match(self, job, profile, evidence_records, context, base_score, screen):
        return MatchResult(score=int(screen.get("screen_score", base_score)), recommendation="APPLY",
                           source="ai_screen", analysis_version="1.8.2", evaluation_stage="screen",
                           screen_score=int(screen.get("screen_score", 0)), screen_decision="PROMOTE",
                           language_fit=100, evidence_ids=[str(x.get("id")) for x in evidence_records[:4] if x.get("id")],
                           **self._ctx(context))

    def select_evidence(self, job, profile, registry, context, lexical, limit=16):
        return [str(x.get("id")) for x in lexical[:limit] if x.get("id")]

    def match(self, job, profile, evidence_records, context=None, base_score=0, screen_data=None):
        context = context or {}
        return MatchResult(score=90, recommendation="APPLY", source="codex_cli",
                           analysis_version="1.8.2", evaluation_stage="deep", deep_pending=False,
                           screen_score=int((screen_data or {}).get("screen_score", 0)), screen_decision="PROMOTE",
                           language_fit=100, technical_fit=90, experience_fit=90, education_fit=95,
                           evidence_ids=[str(x.get("id")) for x in evidence_records[:4] if x.get("id")],
                           **self._ctx(context))


class V182Tests(unittest.TestCase):
    def _cfg(self):
        cfg = load_config(str(PROJECT_ROOT / "config.yaml"))
        cfg["search"]["verify_live_page"] = False
        # V1.9 no longer uses the legacy SCREEN tier. Tests keep the direct-DEEP
        # budget deliberately tiny so allocation/retry behavior is deterministic.
        cfg["ai"]["strategy"]["max_new_deep_per_run"] = 1
        cfg["ai"]["strategy"]["deep_min_pre_score"] = 0
        cfg["ai"]["strategy"]["deep_min_local_priority"] = 0
        cfg["ai"]["strategy"]["reserve_calls_for_new_packages"] = 0
        cfg["ai"]["strategy"]["max_new_packages_per_run"] = 1
        cfg["ai"]["strategy"]["skip_deep_if_german_c1_gap"] = False
        cfg["priority"]["package_generation_min"] = 74
        cfg["notifications"]["immediate_priority_min"] = 82
        return cfg

    @staticmethod
    def _jobs():
        now = datetime.now(timezone.utc)
        return [
            Job("fake", "a", "Mechanical Engineer Alpha", "A", "Berlin, DE", "https://example.com/a",
                description="mechanical engineering CAD machinery structural analysis", published_at=now),
            Job("fake", "b", "Mechanical Engineer Beta", "B", "Berlin, DE", "https://example.com/b",
                description="mechanical engineering CAD machinery structural analysis", published_at=now),
            Job("fake", "c", "Mechanical Engineer Gamma", "C", "Berlin, DE", "https://example.com/c",
                description="mechanical engineering CAD machinery structural analysis", published_at=now),
        ]

    def test_global_deep_budget_selects_best_screen_not_first_job(self):
        with tempfile.TemporaryDirectory() as td:
            old = Path.cwd(); os.chdir(td)
            try:
                Path("input").mkdir()
                # Use absolute paths for project inputs after changing cwd.
                cfg = self._cfg()
                root = PROJECT_ROOT
                cfg["documents"]["profile"] = str(root / "input/profile.json")
                cfg["search"]["career_scope_file"] = str(root / "input/career_scope.yaml")
                cfg["evidence"]["registry"] = str(root / "input/evidence/evidence.json")
                cfg["priority"]["package_generation_min"] = 101
                db = Database("output/test.db")
                scores = lambda job, profile, cfg_: {"Mechanical Engineer Alpha": 65, "Mechanical Engineer Beta": 75, "Mechanical Engineer Gamma": 85}[job.title]
                with patch("src.pipeline.build_sources", return_value=[_FakeSource(self._jobs())]), \
                     patch("src.pipeline.AIEngine", _FakeAI), patch("src.pipeline.heuristic_score", side_effect=scores):
                    result = run_pipeline(cfg, db, dry_run=False)
                rows = {r["title"]: r for r in db.top_jobs(20)}
                self.assertEqual(result["ai_screened"], 0)
                self.assertEqual(result["deep_ai_evaluated"], 1)
                self.assertEqual(json.loads(rows["Mechanical Engineer Gamma"]["match_json"])["evaluation_stage"], "deep")
                self.assertEqual(json.loads(rows["Mechanical Engineer Alpha"]["match_json"])["evaluation_stage"], "pre")
                self.assertTrue(json.loads(rows["Mechanical Engineer Alpha"]["match_json"])["deep_pending"])
                db.close()
            finally:
                os.chdir(old)


    def test_deep_pending_screen_is_retried_next_run_without_new_screen(self):
        with tempfile.TemporaryDirectory() as td:
            old = Path.cwd(); os.chdir(td)
            try:
                cfg = self._cfg(); root = PROJECT_ROOT
                cfg["documents"]["profile"] = str(root / "input/profile.json")
                cfg["search"]["career_scope_file"] = str(root / "input/career_scope.yaml")
                cfg["evidence"]["registry"] = str(root / "input/evidence/evidence.json")
                cfg["priority"]["package_generation_min"] = 101
                db = Database("output/test.db")
                scores = lambda job, profile, cfg_: {"Mechanical Engineer Alpha": 65, "Mechanical Engineer Beta": 75, "Mechanical Engineer Gamma": 85}[job.title]
                with patch("src.pipeline.build_sources", return_value=[_FakeSource(self._jobs())]), patch("src.pipeline.AIEngine", _FakeAI), patch("src.pipeline.heuristic_score", side_effect=scores):
                    first = run_pipeline(cfg, db, dry_run=False)
                    second = run_pipeline(cfg, db, dry_run=False)
                rows = {r["title"]: json.loads(r["match_json"]) for r in db.top_jobs(20)}
                self.assertEqual(first["ai_screened"], 0)
                # On run two, Gamma is cached deep; Beta wins the one new direct-DEEP slot.
                self.assertEqual(rows["Mechanical Engineer Beta"]["evaluation_stage"], "deep")
                self.assertEqual(second["ai_screened"], 0)
                self.assertEqual(second["deep_ai_evaluated"], 1)
                db.close()
            finally:
                os.chdir(old)

    def test_match_only_reports_would_generate_but_writes_no_application_files(self):
        with tempfile.TemporaryDirectory() as td:
            old = Path.cwd(); os.chdir(td)
            try:
                cfg = self._cfg(); root = PROJECT_ROOT
                cfg["documents"]["profile"] = str(root / "input/profile.json")
                cfg["search"]["career_scope_file"] = str(root / "input/career_scope.yaml")
                cfg["evidence"]["registry"] = str(root / "input/evidence/evidence.json")
                db = Database("output/test.db")
                with patch("src.pipeline.build_sources", return_value=[_FakeSource(self._jobs())]), \
                     patch("src.pipeline.AIEngine", _FakeAI):
                    result = run_pipeline(cfg, db, dry_run=True)
                self.assertEqual(result["execution_mode"], "LOCAL_PREVIEW")
                self.assertEqual(result["ready_packages"], 0)
                self.assertEqual(result["deep_ai_evaluated"], 0)
                self.assertEqual(result["ai_screened"], 0)
                self.assertEqual(result["usage_this_run"]["calls"], 0)
                self.assertFalse(Path("output/applications").exists())
                report = json.loads(Path("output/last_run_report.json").read_text(encoding="utf-8"))
                self.assertFalse(report["document_generation_enabled"])
                self.assertEqual(report["notifications_sent"], 0)
                db.close()
            finally:
                os.chdir(old)

    def test_full_mode_generates_package_and_notification_for_high_deep_match(self):
        with tempfile.TemporaryDirectory() as td:
            old = Path.cwd(); os.chdir(td)
            try:
                cfg = self._cfg(); root = PROJECT_ROOT
                cfg["documents"]["profile"] = str(root / "input/profile.json")
                cfg["search"]["career_scope_file"] = str(root / "input/career_scope.yaml")
                cfg["evidence"]["registry"] = str(root / "input/evidence/evidence.json")
                db = Database("output/test.db")

                def fake_generate(job, match, profile, cfg, ai, fp, source_cv, evidence_items=None, audit_evidence_items=None):
                    pkg = Path("output/applications/fake") / job.source_id
                    pkg.mkdir(parents=True, exist_ok=True)
                    (pkg / "CV_test.tex").write_text("% cv", encoding="utf-8")
                    (pkg / "CoverLetter_test.tex").write_text("% cover", encoding="utf-8")
                    (pkg / "package_status.json").write_text(json.dumps({"ready": True, "semantic_evidence_audit_ok": True}), encoding="utf-8")
                    return pkg, {"ready": True}

                with patch("src.pipeline.build_sources", return_value=[_FakeSource(self._jobs())]), \
                     patch("src.pipeline.AIEngine", _FakeAI), \
                     patch("src.pipeline.generate_package", side_effect=fake_generate), \
                     patch("src.pipeline.notify", return_value=True):
                    result = run_pipeline(cfg, db, dry_run=False)
                self.assertEqual(result["execution_mode"], "FULL_APPLICATION_PREP")
                self.assertEqual(result["ready_packages"], 1)
                self.assertEqual(result["notifications_sent"], 1)
                self.assertTrue(any(Path("output/applications").rglob("CV_test.tex")))
                self.assertTrue(any(Path("output/applications").rglob("CoverLetter_test.tex")))
                db.close()
            finally:
                os.chdir(old)

    def test_customer_support_and_tender_manager_are_local_rejects(self):
        cfg = self._cfg()
        j1 = Job("x", "1", "Founding Customer Support Engineer", "X", "Munich", "https://example.com/1")
        j2 = Job("x", "2", "Tender Manager Renewable Energy", "X", "Hamburg", "https://example.com/2")
        self.assertFalse(title_relevance_gate(j1, cfg).keep)
        self.assertFalse(title_relevance_gate(j2, cfg).keep)

    def test_ba_title_cleanup_after_company_becomes_known(self):
        self.assertEqual(
            _clean_ba_title("Mechanical Design Engineer (m/w/d) bei Loesche GmbH", "Loesche GmbH"),
            "Mechanical Design Engineer (m/w/d)",
        )

    def test_windows_safe_document_layout_for_long_jobtimum_path(self):
        with tempfile.TemporaryDirectory() as td:
            old = Path.cwd()
            # Simulate a fairly deep Windows-style project location by nesting the temp root.
            deep = Path(td) / ("job_agent_project_" + "x" * 55) / ("nested_" + "y" * 35)
            deep.mkdir(parents=True)
            os.chdir(deep)
            try:
                job = Job(
                    "arbeitsagentur", "x",
                    "Mechanical Design Engineer (m/w/d) Maritime Systems",
                    "Jobtimum GmbH Technik & Engineering",
                    "Bremen, DE", "https://example.com/job",
                )
                pkg, tag = _package_layout(Path("output/applications"), "2026-08-14", job, "9838c331aad03974b63131f1", "DE")
                target = pkg / f"CoverLetter_{tag}.tex"
                self.assertLessEqual(len(str(target.resolve())), 245)
                pkg.mkdir(parents=True, exist_ok=True)
                target.write_text("test", encoding="utf-8")
                self.assertTrue(target.exists())
            finally:
                os.chdir(old)

    def test_package_generation_error_does_not_abort_full_pipeline(self):
        with tempfile.TemporaryDirectory() as td:
            old = Path.cwd(); os.chdir(td)
            try:
                cfg = self._cfg(); root = PROJECT_ROOT
                cfg["documents"]["profile"] = str(root / "input/profile.json")
                cfg["search"]["career_scope_file"] = str(root / "input/career_scope.yaml")
                cfg["evidence"]["registry"] = str(root / "input/evidence/evidence.json")
                db = Database("output/test.db")
                with patch("src.pipeline.build_sources", return_value=[_FakeSource(self._jobs())]), \
                     patch("src.pipeline.AIEngine", _FakeAI), \
                     patch("src.pipeline.generate_package", side_effect=FileNotFoundError("simulated long Windows path")), \
                     patch("src.pipeline.notify", return_value=False):
                    result = run_pipeline(cfg, db, dry_run=False)
                self.assertEqual(result["package_generation_errors"], 1)
                self.assertTrue(Path("output/last_run_report.json").exists())
                self.assertTrue(any(Path("output/package_errors").rglob("*.json")))
                db.close()
            finally:
                os.chdir(old)


if __name__ == "__main__":
    unittest.main()
