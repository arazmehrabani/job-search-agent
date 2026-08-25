from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.ai import AIEngine
from src.ai_budget import AIBudgetGuard, AIBudgetExceeded
from src.config import load_config
from src.cv_sources import CVSource
from src.db import Database
from src.documents import _local_trace_audit, generate_package
from src.models import Job, MatchResult
from src.pipeline import run_pipeline, resume_application_packages

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class OneSource:
    name = "fake"
    category = "broad"
    def __init__(self, jobs): self.jobs = list(jobs)
    def health(self):
        return {"name":"fake","category":"broad","automatic":True,"configured":True,"operational":True,"reason":"test"}
    def search_many(self, queries, locations, limit): return list(self.jobs)


class GuardedFakeAI:
    match_calls = 0
    def __init__(self, cfg, usage_recorder=None):
        self.cfg=cfg; self.enabled=True; self.usage_recorder=usage_recorder
    def backend_name(self): return "codex_cli"
    def budget_remaining_calls(self): return 100
    def budget_snapshot(self): return {"locked":False,"remaining_calls":100,"max_calls_per_run":6}
    def heuristic_match(self, job, profile, context, evidence_ids=None):
        return MatchResult(
            score=80,recommendation="REVIEW",source="heuristic",analysis_version="1.9.0",evaluation_stage="pre",
            evidence_ids=list(evidence_ids or []),language_fit=100,
            job_language=context.get("job_language","en"),employment_type=context.get("employment_type","professional"),
            career_family=context.get("career_family","mechanical_product_development"),
            career_family_label=context.get("career_family_label","Mechanical"),career_tier=context.get("career_tier","core"),
            source_cv=context.get("source_cv","mechanical_en"),german_requirement=context.get("german_requirement","none"),
            career_stage=context.get("career_stage","professional"),schedule=context.get("schedule","full_time"),contract=context.get("contract","regular"),
        )
    def match(self, job, profile, evidence_records, context=None, base_score=0, screen_data=None):
        type(self).match_calls += 1
        c=context or {}
        return MatchResult(
            score=88,recommendation="APPLY",decision="APPLY",source="codex_cli",analysis_version="1.9.0",evaluation_stage="deep",
            evidence_ids=[str(x.get("id")) for x in evidence_records[:4] if x.get("id")],technical_fit=90,experience_fit=88,language_fit=90,education_fit=95,
            job_language=c.get("job_language","en"),employment_type=c.get("employment_type","professional"),career_family=c.get("career_family","mechanical_product_development"),
            career_family_label=c.get("career_family_label","Mechanical"),career_tier=c.get("career_tier","core"),source_cv=c.get("source_cv","mechanical_en"),
            german_requirement=c.get("german_requirement","none"),career_stage=c.get("career_stage","professional"),schedule=c.get("schedule","full_time"),contract=c.get("contract","regular"),
        )
    def screen(self,*a,**k): raise AssertionError("V1.9 normal pipeline must not call SCREEN")
    def select_evidence(self,*a,**k): raise AssertionError("V1.9 normal pipeline must not call semantic evidence selection")


class V190Tests(unittest.TestCase):
    def cfg(self):
        cfg=load_config(str(PROJECT_ROOT/"config.yaml"))
        cfg["search"]["verify_live_page"]=False
        cfg["search"]["auto_from_cv"]=False
        cfg["documents"]["profile"]=str(PROJECT_ROOT/"input/profile.json")
        cfg["search"]["career_scope_file"]=str(PROJECT_ROOT/"input/career_scope.yaml")
        cfg["evidence"]["registry"]=str(PROJECT_ROOT/"input/evidence/evidence.json")
        cfg["priority"]["package_generation_min"]=74
        cfg["ai"]["strategy"]["max_new_deep_per_run"]=3
        cfg["ai"]["strategy"]["deep_min_pre_score"]=0
        cfg["ai"]["strategy"]["deep_min_local_priority"]=0
        cfg["ai"]["strategy"]["reserve_calls_for_new_packages"]=0
        cfg["ai"]["strategy"]["max_new_packages_per_run"]=3
        cfg["ai"]["strategy"]["skip_deep_if_german_c1_gap"]=True
        cfg["notifications"]["desktop"]=False
        return cfg

    @staticmethod
    def jobs(n=3):
        now=datetime.now(timezone.utc)
        return [Job("fake",str(i),f"Mechanical Design Engineer {i}",f"Company {i}","Berlin, DE",f"https://example.com/{i}",
                    description="mechanical design CAD machinery structural analysis manufacturing drawings",published_at=now) for i in range(n)]

    def test_shipped_public_usage_hint_starts_locked(self):
        cfg=self.cfg()
        with tempfile.TemporaryDirectory() as td:
            cfg["ai"]["budget"]["ledger_file"]=str(Path(td)/"ledger.jsonl")
            guard=AIBudgetGuard(cfg)
            self.assertTrue(guard.locked)
            snap=guard.snapshot()
            self.assertEqual(snap["usage_hint_percent"],0.0)
            self.assertEqual(snap["remaining_calls"],0)

    def test_global_ledger_prevents_new_folder_from_resetting_daily_budget(self):
        with tempfile.TemporaryDirectory() as td:
            hint=Path(td)/"hint.json"
            hint.write_text(json.dumps({"remaining_percent":100,"resets_on":"2099-01-01","period_started_on":datetime.now().date().isoformat()}),encoding="utf-8")
            ledger=Path(td)/"global.jsonl"
            cfg=self.cfg(); b=cfg["ai"]["budget"]
            b.update({"usage_hint_file":str(hint),"ledger_file":str(ledger),"max_calls_per_run":10,"max_provider_calls_per_day":2,
                      "max_provider_calls_per_allowance_period":10,"max_estimated_input_tokens_per_day":999999,"max_estimated_input_tokens_per_allowance_period":999999})
            g1=AIBudgetGuard(cfg); g1.reserve("a",100); g1.reserve("b",100)
            g2=AIBudgetGuard(cfg)
            self.assertTrue(g2.locked)
            self.assertIn("daily",g2.snapshot()["lock_reason"].lower())

    def test_ai_budget_blocks_second_call_before_subprocess(self):
        with tempfile.TemporaryDirectory() as td:
            hint=Path(td)/"hint.json"; ledger=Path(td)/"ledger.jsonl"
            hint.write_text(json.dumps({"remaining_percent":100,"resets_on":"2099-01-01","period_started_on":datetime.now().date().isoformat()}),encoding="utf-8")
            cfg=self.cfg(); cfg["ai"]["budget"].update({"usage_hint_file":str(hint),"ledger_file":str(ledger),"max_calls_per_run":1,
                "max_provider_calls_per_day":10,"max_provider_calls_per_allowance_period":10,"max_estimated_input_tokens_per_run":999999,
                "max_estimated_input_tokens_per_day":999999,"max_estimated_input_tokens_per_allowance_period":999999})
            fake=SimpleNamespace(returncode=0,stdout='{"ok": true}',stderr='')
            with patch("src.ai.find_codex_executable",return_value="codex"), patch("src.ai.subprocess.run",return_value=fake) as sprun:
                ai=AIEngine(cfg)
                ai._text_call("x",{"a":1},operation="first")
                with self.assertRaises(AIBudgetExceeded): ai._text_call("x",{"a":2},operation="second")
                self.assertEqual(sprun.call_count,1)

    def test_local_preview_is_zero_ai_even_with_enabled_fake(self):
        with tempfile.TemporaryDirectory() as td:
            old=Path.cwd(); os.chdir(td)
            try:
                GuardedFakeAI.match_calls=0
                cfg=self.cfg(); db=Database("output/test.db")
                with patch("src.pipeline.build_sources",return_value=[OneSource(self.jobs(1))]), patch("src.pipeline.AIEngine",GuardedFakeAI):
                    r=run_pipeline(cfg,db,dry_run=True)
                self.assertEqual(r["execution_mode"],"LOCAL_PREVIEW")
                self.assertEqual(r["deep_ai_evaluated"],0)
                self.assertEqual(GuardedFakeAI.match_calls,0)
                self.assertFalse(Path("output/applications").exists())
                db.close()
            finally: os.chdir(old)

    def test_normal_run_never_regenerates_existing_needs_review_package(self):
        with tempfile.TemporaryDirectory() as td:
            old=Path.cwd(); os.chdir(td)
            try:
                GuardedFakeAI.match_calls=0
                cfg=self.cfg(); db=Database("output/test.db"); job=self.jobs(1)[0]
                fp=db.upsert_job(job)
                m=MatchResult(score=88,recommendation="APPLY",priority_score=84,priority_label="HIGH",source="codex_cli",evaluation_stage="deep",deep_pending=False,
                              analysis_version="1.8.3",job_language="en",employment_type="professional",career_family="mechanical_product_development",career_tier="core",source_cv="mechanical_en")
                db.set_match(fp,m); db.record_application(fp,"output/applications/existing","needs_ai_or_review")
                with patch("src.pipeline.build_sources",return_value=[OneSource([job])]), patch("src.pipeline.AIEngine",GuardedFakeAI), patch("src.pipeline.generate_package") as gen:
                    r=run_pipeline(cfg,db,dry_run=False)
                gen.assert_not_called()
                self.assertGreaterEqual(r["existing_packages_skipped"],1)
                self.assertEqual(GuardedFakeAI.match_calls,0)
                db.close()
            finally: os.chdir(old)

    def test_explicit_repair_is_only_route_to_regenerate_existing_package_and_is_capped(self):
        with tempfile.TemporaryDirectory() as td:
            old=Path.cwd(); os.chdir(td)
            try:
                cfg=self.cfg(); cfg["ai"]["strategy"]["max_repair_packages_per_run"]=1
                db=Database("output/test.db")
                for job in self.jobs(2):
                    fp=db.upsert_job(job)
                    m=MatchResult(score=88,recommendation="APPLY",priority_score=84,priority_label="HIGH",source="codex_cli",evaluation_stage="deep",deep_pending=False,
                                  job_language="en",employment_type="professional",career_family="mechanical_product_development",career_tier="core",source_cv="mechanical_en")
                    db.set_match(fp,m); db.record_application(fp,f"output/applications/{job.source_id}","needs_ai_or_review")
                def fake_gen(job,match,profile,cfg,ai,fp,source_cv,evidence_items=None,audit_evidence_items=None):
                    p=Path("output/repaired")/job.source_id; p.mkdir(parents=True,exist_ok=True); return p,{"ready":True}
                with patch("src.pipeline.AIEngine",GuardedFakeAI), patch("src.pipeline.generate_package",side_effect=fake_gen) as gen:
                    r=resume_application_packages(cfg,db,repair_existing=True)
                self.assertEqual(gen.call_count,1)
                self.assertEqual(r["packages_ready"],1)
                self.assertEqual(len(r["budget_deferred"]),1)
                db.close()
            finally: os.chdir(old)

    def test_normal_pipeline_has_no_screen_or_semantic_selection_stage(self):
        with tempfile.TemporaryDirectory() as td:
            old=Path.cwd(); os.chdir(td)
            try:
                GuardedFakeAI.match_calls=0
                cfg=self.cfg(); cfg["priority"]["package_generation_min"]=101; db=Database("output/test.db")
                with patch("src.pipeline.build_sources",return_value=[OneSource(self.jobs(2))]), patch("src.pipeline.AIEngine",GuardedFakeAI):
                    r=run_pipeline(cfg,db,dry_run=False)
                self.assertEqual(r["ai_screened"],0)
                self.assertGreater(GuardedFakeAI.match_calls,0)
                ops={x["operation"] for x in r["usage_by_operation_this_run"]}
                self.assertNotIn("job_screen",ops); self.assertNotIn("evidence_semantic_selection",ops)
                db.close()
            finally: os.chdir(old)

    def test_explicit_c1_german_gap_is_local_no_deep_unless_user_overrides(self):
        with tempfile.TemporaryDirectory() as td:
            old=Path.cwd(); os.chdir(td)
            try:
                GuardedFakeAI.match_calls=0
                cfg=self.cfg(); cfg["priority"]["package_generation_min"]=101; db=Database("output/test.db")
                j=self.jobs(1)[0]; j.description += " Fluent German C1 required."
                with patch("src.pipeline.build_sources",return_value=[OneSource([j])]), patch("src.pipeline.AIEngine",GuardedFakeAI), patch("src.pipeline.heuristic_score",return_value=90):
                    r=run_pipeline(cfg,db,dry_run=False)
                self.assertEqual(r["deep_ai_evaluated"],0)
                self.assertEqual(GuardedFakeAI.match_calls,0)
                db.close()
            finally: os.chdir(old)

    def test_new_package_cap_queues_excess_without_regenerating(self):
        with tempfile.TemporaryDirectory() as td:
            old=Path.cwd(); os.chdir(td)
            try:
                GuardedFakeAI.match_calls=0
                cfg=self.cfg(); cfg["ai"]["strategy"]["max_new_packages_per_run"]=1; db=Database("output/test.db")
                def fake_gen(job,match,profile,cfg,ai,fp,source_cv,evidence_items=None,audit_evidence_items=None):
                    p=Path("output/apps")/job.source_id; p.mkdir(parents=True,exist_ok=True); return p,{"ready":True}
                with patch("src.pipeline.build_sources",return_value=[OneSource(self.jobs(3))]), patch("src.pipeline.AIEngine",GuardedFakeAI), patch("src.pipeline.generate_package",side_effect=fake_gen) as gen:
                    r=run_pipeline(cfg,db,dry_run=False)
                self.assertEqual(gen.call_count,1)
                self.assertGreaterEqual(len(r["queued_new_packages"]),1)
                db.close()
            finally: os.chdir(old)

    def test_single_application_bundle_creates_both_documents_with_local_trace_audit(self):
        class BundleAI:
            def __init__(self): self.enabled=True; self.last_bundle_error=""; self.calls=0
            def backend_name(self): return "codex_cli"
            def application_bundle(self,*args,**kwargs):
                self.calls += 1
                return {
                    "cv_latex":"\\documentclass{article}\\begin{document}Professional Experience: CATIA V5 assemblies.\\end{document}",
                    "cv_evidence_ids_used":["E1"],"cv_claim_trace":[{"claim":"Created CATIA V5 assemblies.","evidence_ids":["E1"]}],
                    "cover_letter":"Dear Hiring Team,\n\nI created CATIA V5 assemblies in professional mechanical design work.\n\nSincerely,\nREPLACENAME",
                    "cover_letter_evidence_ids_used":["E1"],"cover_letter_claim_trace":[{"claim":"Created CATIA V5 assemblies.","evidence_ids":["E1"]}],
                    "recipient":"Hiring Team","reference":""
                }
        with tempfile.TemporaryDirectory() as td:
            old=Path.cwd(); os.chdir(td)
            try:
                Path("master.tex").write_text("\\documentclass{article}\\begin{document}Professional Experience.\\end{document}",encoding="utf-8")
                src=CVSource("mechanical_en",Path("master.tex"),"en")
                cfg=self.cfg(); cfg["documents"]["compile_pdf"]=False; cfg["documents"]["output_dir"]="output/applications"; cfg["documents"]["assets_dir"]="input/assets"
                cfg["documents"]["cover_letter_templates"]={}
                job=self.jobs(1)[0]
                match=MatchResult(score=88,recommendation="APPLY",source="codex_cli",evaluation_stage="deep",job_language="en",employment_type="professional",career_family="mechanical_product_development",career_family_label="Mechanical",career_tier="core")
                evidence=[{"id":"E1","claim":"Created machine assemblies and manufacturing drawings in CATIA V5.","keywords":["CATIA V5","assemblies"]}]
                ai=BundleAI(); pkg,res=generate_package(job,match,{"name":"REPLACENAME"},cfg,ai,"abcdef123456",src,evidence_items=evidence,audit_evidence_items=evidence)
                self.assertEqual(ai.calls,1)
                self.assertTrue(any(pkg.glob("CV_*.tex")))
                self.assertTrue(any(pkg.glob("CoverLetter_*.tex")))
                self.assertTrue(any(pkg.glob("CoverLetter_*.txt")))
                self.assertTrue(res["evidence_audit_ok"])
                self.assertTrue(res["ready"])
            finally: os.chdir(old)

    def test_local_trace_audit_distinguishes_missing_and_mismatch(self):
        evidence=[{"id":"E1","claim":"Created CATIA V5 assemblies.","keywords":["CATIA V5"]}]
        audit=_local_trace_audit([
            {"document":"cv","claim":"Created CATIA V5 assemblies.","evidence_ids":["E1"]},
            {"document":"cv","claim":"Used Nastran for certification.","evidence_ids":["E1"]},
            {"document":"cover_letter","claim":"English C1.","evidence_ids":[]},
        ],evidence)
        statuses=[x["status"] for x in audit["results"]]
        self.assertIn("SUPPORTED_TRACE",statuses)
        self.assertIn("TRACE_MISMATCH",statuses)
        self.assertIn("TRACE_MISSING",statuses)


if __name__ == "__main__": unittest.main()
