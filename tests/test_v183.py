from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from src.ai import AIEngine
from src.config import load_config
from src.db import Database
from src.documents import compile_latex, letter_to_tex, pdf_page_count
from src.models import Job, MatchResult
from src.pipeline import resume_application_packages

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class _RecoveryAI:
    def __init__(self, cfg, usage_recorder=None):
        self.cfg = cfg
        self.enabled = True
        self.usage_recorder = usage_recorder
    def backend_name(self):
        return "codex_cli"


class V183Tests(unittest.TestCase):
    def test_preferred_cover_letter_templates_are_sanitized_and_compile(self):
        cfg = load_config(str(PROJECT_ROOT / "config.yaml"))
        profile = json.loads((PROJECT_ROOT / "input/profile.json").read_text(encoding="utf-8"))
        for lang in ("de", "en"):
            job = Job("x", "1", "Mechanical Design Engineer (m/w/d)", "Example Engineering GmbH",
                      "Hamburg, DE", "https://example.com/job")
            match = MatchResult(score=82, recommendation="REVIEW", job_language=lang,
                                career_family="mechanical_product_development",
                                career_family_label="Mechanical design")
            letter = (
                "Sehr geehrte Damen und Herren,\n\n"
                "Die Position verbindet mechanische Entwicklung, Konstruktion und technische Analyse.\n\n"
                "In meiner bisherigen Tätigkeit entwickelte ich mechanische Systeme und Fertigungsunterlagen.\n\n"
                "Mit freundlichen Grüßen\nREPLACENAME"
                if lang == "de" else
                "Dear Recruiting Team,\n\n"
                "The position combines mechanical development, design and engineering analysis.\n\n"
                "In my previous work I developed mechanical systems and manufacturing documentation.\n\n"
                "Sincerely,\nREPLACENAME"
            )
            with tempfile.TemporaryDirectory() as td:
                old = Path.cwd(); os.chdir(PROJECT_ROOT)
                try:
                    tex = letter_to_tex(letter, profile, job, lang, cfg=cfg, metadata={}, match=match)
                finally:
                    os.chdir(old)
                self.assertIn("REPLACENAME", tex)
                self.assertIn("Example Engineering GmbH", tex)
                self.assertIn("Mechanical Design Engineer", tex)
                self.assertNotIn("436 3238", tex)  # real example contact data must not leak into shipped templates
                p = Path(td) / f"letter_{lang}.tex"
                p.write_text(tex, encoding="utf-8")
                ok, log = compile_latex(p)
                self.assertTrue(ok, log[-1000:])
                self.assertEqual(pdf_page_count(p.with_suffix(".pdf")), 1)

    def test_semantic_audit_can_repair_trace_without_rejecting_truthful_content(self):
        cfg = load_config(str(PROJECT_ROOT / "config.yaml"))
        ai = AIEngine(cfg)
        ai.enabled = True
        evidence = [{"id": "EXP_MECH_002", "claim": "Created machine assemblies and manufacturing drawings in CATIA V5.", "verified": True}]
        response = {
            "results": [{
                "document": "cover_letter",
                "claim": "Created machine assemblies and manufacturing drawings in CATIA V5.",
                "category": "TRACE_MISMATCH",
                "supported": True,
                "severity": "none",
                "recommended_evidence_ids": ["EXP_MECH_002"],
                "reason": "The content is supported but the original trace was wrong.",
                "suggested_revision": "",
            }],
            "overall_ok": True,
        }
        with patch.object(ai, "_text_call", return_value=json.dumps(response)):
            audit = ai.audit_claims([{"document": "cover_letter", "claim": response["results"][0]["claim"], "evidence_ids": []}], evidence)
        self.assertTrue(audit["ok"])
        self.assertEqual(audit["trace_repairs"][0]["category"], "TRACE_MISMATCH")
        self.assertEqual(audit["trace_repairs"][0]["recommended_evidence_ids"], ["EXP_MECH_002"])
        self.assertEqual(audit["unsupported"], [])

    def test_repair_existing_packages_reuses_cached_deep_match_and_updates_last_run_report(self):
        with tempfile.TemporaryDirectory() as td:
            old = Path.cwd(); os.chdir(td)
            try:
                cfg = load_config(str(PROJECT_ROOT / "config.yaml"))
                cfg["documents"]["profile"] = str(PROJECT_ROOT / "input/profile.json")
                cfg["documents"]["cv_sources"]["mechanical_en"]["path"] = str(PROJECT_ROOT / "input/cvs/mechanical_en_master.tex")
                cfg["evidence"]["registry"] = str(PROJECT_ROOT / "input/evidence/evidence.json")
                cfg["notifications"]["desktop"] = False
                db = Database("output/test.db")
                job = Job("fake", "abc", "Mechanical Engineer", "Example GmbH", "Berlin, DE",
                          "https://example.com/job", description="mechanical design CATIA", published_at=datetime.now(timezone.utc))
                fp = db.upsert_job(job)
                match = MatchResult(score=86, recommendation="APPLY", source="codex_cli", analysis_version="1.8.2",
                                    evaluation_stage="deep", deep_pending=False, priority_score=85, priority_label="HIGH",
                                    job_language="en", employment_type="professional",
                                    career_family="mechanical_product_development", career_family_label="Mechanical design",
                                    source_cv="mechanical_en")
                db.set_match(fp, match)
                db.record_application(fp, "output/applications/old", status="needs_ai_or_review")

                def fake_generate(job, match, profile, cfg, ai, fp, source_cv, evidence_items=None, audit_evidence_items=None):
                    pkg = Path("output/applications/repaired")
                    pkg.mkdir(parents=True, exist_ok=True)
                    (pkg / "package_status.json").write_text(json.dumps({"ready": True}), encoding="utf-8")
                    return pkg, {"ready": True, "notes": []}

                with patch("src.pipeline.AIEngine", _RecoveryAI), patch("src.pipeline.generate_package", side_effect=fake_generate):
                    report = resume_application_packages(cfg, db, repair_existing=True)
                self.assertEqual(report["mode"], "REPAIR_EXISTING_PACKAGES")
                self.assertEqual(report["packages_ready"], 1)
                last = json.loads(Path("output/last_run_report.json").read_text(encoding="utf-8"))
                self.assertEqual(last["execution_mode"], "REPAIR_EXISTING_PACKAGES")
                self.assertTrue(last["document_generation_enabled"])
                self.assertEqual(last["http"]["network_requests"], 0)
                db.close()
            finally:
                os.chdir(old)


if __name__ == "__main__":
    unittest.main()
