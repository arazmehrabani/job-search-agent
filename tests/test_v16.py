from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.ai import AIEngine
from src.config import load_config
from src.dashboard import build_dashboard
from src.dashboard_server import validate_feedback_payload
from src.db import Database
from src.http_policy import HttpPolicy
from src.models import Job, MatchResult
from src.pagecheck import PageChecker
from src.priority import calculate_priority
from src.utils import canonical_url, is_safe_http_url


class V16ReliabilityTests(unittest.TestCase):
    def test_url_scheme_restriction(self):
        self.assertFalse(is_safe_http_url("javascript:alert(1)"))
        self.assertFalse(is_safe_http_url("file:///C:/secret.txt"))
        self.assertEqual(canonical_url("javascript:alert(1)"), "")
        self.assertTrue(is_safe_http_url("https://example.com/jobs/1"))

    def test_database_rejects_unsafe_job_url(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(str(Path(td) / "x.db"))
            with self.assertRaises(ValueError):
                db.upsert_job(Job("manual", "1", "Role", "ACME", "Berlin", "javascript:alert(1)"))
            db.close()

    def test_dashboard_does_not_render_unsafe_href(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(str(Path(td) / "x.db"))
            fp = db.upsert_job(Job("manual", "1", "Role", "ACME", "Berlin", "https://example.com/job"))
            db.conn.execute("UPDATE jobs SET url=? WHERE fingerprint=?", ("javascript:alert(1)", fp))
            db.conn.commit()
            out = Path(td) / "dash.html"
            build_dashboard(db, str(out), feedback_token="abc")
            text = out.read_text(encoding="utf-8")
            self.assertNotIn("href='javascript:", text)
            self.assertIn("X-Job-Agent-Token", text)
            db.close()

    def test_feedback_payload_validation(self):
        fp = "a" * 24
        self.assertEqual(validate_feedback_payload({"fingerprint": fp, "decision": "apply", "reason": " ok "}), (fp, "APPLY", "ok"))
        with self.assertRaises(ValueError):
            validate_feedback_payload({"fingerprint": "bad", "decision": "APPLY"})
        with self.assertRaises(ValueError):
            validate_feedback_payload({"fingerprint": fp, "decision": "DROP_TABLE"})
        with self.assertRaises(ValueError):
            validate_feedback_payload({"fingerprint": fp, "decision": "SKIP", "reason": "x" * 1001})

    def test_per_host_throttle_is_applied(self):
        cfg = {"http": {"min_delay_per_host_seconds": 1.0, "delay_jitter_seconds": 0, "max_retries": 0,
                         "page_cache_minutes": 0, "respect_robots_txt": False}}
        policy = HttpPolicy(cfg)
        response = Mock(status_code=200, text="ok", url="https://example.com/job", headers={})
        policy.session.get = Mock(return_value=response)
        with patch("src.http_policy.time.sleep") as sleep:
            policy.fetch("https://example.com/job/1")
            policy.fetch("https://example.com/job/2")
        self.assertTrue(sleep.called)
        self.assertGreaterEqual(sleep.call_args.args[0], 0.9)

    def test_page_cache_prevents_repeat_fetch(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = {"http": {"min_delay_per_host_seconds": 0, "max_retries": 0, "page_cache_minutes": 60,
                             "respect_robots_txt": False, "cache_file": str(Path(td) / "cache.json")}}
            policy = HttpPolicy(cfg)
            response = Mock(status_code=200, text="<html>cached</html>", url="https://example.com/job", headers={})
            policy.session.get = Mock(return_value=response)
            first = policy.fetch("https://example.com/job")
            second = policy.fetch("https://example.com/job")
            self.assertFalse(first.from_cache)
            self.assertTrue(second.from_cache)
            self.assertEqual(policy.session.get.call_count, 1)

    def test_robots_disallow_stops_job_fetch(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = {"http": {"min_delay_per_host_seconds": 0, "max_retries": 0, "page_cache_minutes": 0,
                             "respect_robots_txt": True, "robots_fail_open": False,
                             "cache_file": str(Path(td) / "cache.json")}}
            policy = HttpPolicy(cfg)
            robots = Mock(status_code=200, text="User-agent: *\nDisallow: /private", url="https://example.com/robots.txt", headers={})
            policy.session.get = Mock(return_value=robots)
            checker = PageChecker(cfg, policy=policy)
            status, out = checker.check_and_enrich(Job("manual", "", "Role", "ACME", "", "https://example.com/private/job"))
            self.assertEqual(status, "robots_disallowed")
            self.assertEqual(out.metadata.get("pagecheck_error"), "robots_disallowed")
            self.assertEqual(policy.session.get.call_count, 1)

    def test_semantic_evidence_selection_can_recover_non_keyword_match(self):
        cfg = load_config("config.yaml")
        ai = AIEngine({**cfg, "ai": {**cfg.get("ai", {}), "provider": "heuristic"}})
        ai.enabled = True
        ai._text_call = Mock(return_value=json.dumps({"evidence_ids": ["E_SEM"]}))
        evidence = [
            {"id": "E_LEX", "claim": "Used CAD for machine design", "verified": True},
            {"id": "E_SEM", "claim": "Analyzed vibration modes and resonance of industrial machinery", "verified": True},
        ]
        job = Job("manual", "1", "Dynamic Behaviour Specialist", "ACME", "Berlin", "https://example.com/job",
                  description="Assess eigen-behaviour and oscillatory response of mechanical systems")
        ids = ai.select_evidence(job, {}, evidence, {}, [evidence[0]], limit=2)
        self.assertEqual(ids[0], "E_SEM")
        self.assertIn("E_LEX", ids)

    def test_semantic_claim_audit_can_block_overstatement(self):
        cfg = load_config("config.yaml")
        ai = AIEngine({**cfg, "ai": {**cfg.get("ai", {}), "provider": "heuristic"}})
        ai.enabled = True
        ai._text_call = Mock(return_value=json.dumps({
            "overall_ok": False,
            "results": [{"claim": "Led manufacturing", "supported": False, "severity": "major",
                         "reason": "Evidence says supported, not led", "suggested_revision": "Supported manufacturing"}],
        }))
        result = ai.audit_claims(
            [{"claim": "Led manufacturing", "evidence_ids": ["E1"]}],
            [{"id": "E1", "claim": "Supported manufacturing and assembly", "verified": True}],
        )
        self.assertFalse(result["ok"])
        self.assertEqual(len(result["unsupported"]), 1)

    def test_contextual_german_risk_affects_priority_softly(self):
        cfg = load_config("config.yaml")
        job = Job("manual", "1", "Engineer", "ACME", "Berlin, Germany", "https://example.com/job")
        base = MatchResult(score=85, recommendation="APPLY", language_fit=55, german_requirement="none",
                           career_tier="core", career_stage="professional", schedule="full_time")
        p1, _, _ = calculate_priority(job, base, cfg)
        contextual = MatchResult(score=85, recommendation="APPLY", language_fit=55, german_requirement="none",
                                 career_tier="core", career_stage="professional", schedule="full_time",
                                 contextual_german_importance="mandatory", contextual_german_mandatory="yes")
        p2, _, reasons = calculate_priority(job, contextual, cfg)
        self.assertLess(p2, p1)
        self.assertTrue(any("contextually important" in r for r in reasons))


if __name__ == "__main__":
    unittest.main()
