from __future__ import annotations
import json
import tempfile
import unittest
from pathlib import Path

from src.config import load_config
from src.models import Job, MatchResult
from src.filters import hard_filter, heuristic_score
from src.relevance import title_relevance_gate, assess_relevance
from src.sources.arbeitnow import ArbeitnowSource
from src.db import Database
from src.dashboard import build_dashboard


class V18RelevanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = load_config("config.yaml")
        cls.profile = json.loads(Path("input/profile.json").read_text(encoding="utf-8"))

    def test_backend_software_title_is_hard_rejected_without_ai(self):
        job = Job("arbeitnow", "x", "Software Engineer, Backend Focused", "On", "Berlin, Germany", "https://example.com/x", description="Python backend cloud services")
        gate = title_relevance_gate(job, self.cfg)
        self.assertFalse(gate.keep)
        self.assertEqual(gate.reason, "PURE_SOFTWARE_BACKEND")
        ok, reason = hard_filter(job, self.cfg)
        self.assertFalse(ok)
        self.assertEqual(reason, "PURE_SOFTWARE_BACKEND")
        self.assertEqual(heuristic_score(job, self.profile, self.cfg), 0)

    def test_software_with_real_simulation_bridge_is_kept(self):
        job = Job("arbeitnow", "x", "Software Engineer (m/w/d) Simulation", "ACME", "Germany", "https://example.com/x", description="Mechanical simulation software for engineering models")
        gate = title_relevance_gate(job, self.cfg)
        self.assertTrue(gate.keep)
        self.assertTrue(assess_relevance(job, self.cfg).keep)
        self.assertGreaterEqual(heuristic_score(job, self.profile, self.cfg), 40)

    def test_control_software_wind_turbines_is_kept(self):
        job = Job("arbeitnow", "x", "Control Software Engineer – Wind Turbines", "ACME", "Germany", "https://example.com/x", description="Control systems and simulation for wind turbines")
        self.assertTrue(title_relevance_gate(job, self.cfg).keep)
        self.assertGreaterEqual(heuristic_score(job, self.profile, self.cfg), 50)

    def test_finance_renewable_energy_is_still_rejected(self):
        job = Job("arbeitnow", "x", "Junior Finance & Accounting Manager Renewable Energy", "ACME", "Germany", "https://example.com/x", description="Finance accounting for renewable energy")
        gate = title_relevance_gate(job, self.cfg)
        self.assertFalse(gate.keep)
        self.assertEqual(gate.reason, "FINANCE_HR_ADMIN")

    def test_professional_job_without_schedule_is_not_filtered(self):
        job = Job("arbeitsagentur", "x", "Mechanical Engineer (m/w/d) Creo", "ACME", "Germany", "https://example.com/x", description="Mechanical design CAD machinery")
        ok, reason = hard_filter(job, self.cfg)
        self.assertTrue(ok, reason)

    def test_relevant_structural_role_scores_far_above_backend(self):
        good = Job("x", "1", "Structural Analysis Engineer", "A", "Germany", "https://example.com/g", description="ANSYS FEA modal harmonic structural dynamics")
        bad = Job("x", "2", "Software Engineer, Backend Focused", "B", "Germany", "https://example.com/b", description="Python cloud backend services")
        self.assertGreaterEqual(heuristic_score(good, self.profile, self.cfg), 70)
        self.assertEqual(heuristic_score(bad, self.profile, self.cfg), 0)

    def test_generic_systems_engineer_needs_domain_description(self):
        weak = Job("x", "1", "Systems Engineer - m/f/d", "A", "Germany", "https://example.com/w", description="enterprise IT services")
        strong = Job("x", "2", "Systems Engineer - m/f/d", "A", "Germany", "https://example.com/s", description="mechanical systems simulation and validation")
        self.assertFalse(assess_relevance(weak, self.cfg).keep)
        self.assertTrue(assess_relevance(strong, self.cfg).keep)

    def test_arbeitnow_mechanical_query_does_not_match_backend_just_for_engineer(self):
        src = ArbeitnowSource({"pages": 1})
        backend = {"title": "Software Engineer, Backend Focused", "description": "Python cloud backend", "tags": [], "job_types": []}
        mechanical = {"title": "Mechanical Engineer", "description": "CAD machinery", "tags": [], "job_types": []}
        self.assertFalse(src._matches_any_query(backend, ["mechanical engineer"]))
        self.assertTrue(src._matches_any_query(mechanical, ["mechanical engineer"]))

    def test_hard_filter_clears_stale_v17_score(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(str(Path(td) / "x.db"))
            job = Job("arbeitnow", "x", "Software Engineer, Backend Focused", "Other", "Berlin", "https://example.com/stale")
            fp = db.upsert_job(job)
            old = MatchResult(score=46, recommendation="SKIP", priority_score=56, priority_label="LOW", source="heuristic")
            db.set_match(fp, old)
            db.set_filter_reason(fp, "PURE_SOFTWARE_BACKEND")
            row = db.conn.execute("SELECT match_score,priority_score,match_json,status FROM jobs WHERE fingerprint=?", (fp,)).fetchone()
            self.assertIsNone(row["match_score"])
            self.assertIsNone(row["priority_score"])
            self.assertIsNone(row["match_json"])
            self.assertEqual(row["status"], "filtered")
            db.close()

    def test_dashboard_hides_rejects_in_audit_section(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(str(Path(td) / "x.db"))
            good = Job("manual", "1", "CAE Engineer", "ACME", "Berlin", "https://example.com/g")
            gfp = db.upsert_job(good); db.set_active(gfp, "active")
            gm = MatchResult(score=84, recommendation="APPLY", priority_score=87, priority_label="HIGH", source="heuristic", career_family_label="CAE")
            db.set_match(gfp, gm)
            bad = Job("arbeitnow", "2", "Software Engineer, Backend Focused", "Other", "Berlin", "https://example.com/b")
            bfp = db.upsert_job(bad); db.set_active(bfp, "unknown"); db.set_filter_reason(bfp, "PURE_SOFTWARE_BACKEND")
            out = Path(td) / "dash.html"
            build_dashboard(db, str(out), cfg=self.cfg)
            text = out.read_text(encoding="utf-8")
            self.assertIn("Jobs worth your attention", text)
            self.assertIn("Rejected / filtered audit", text)
            # Both remain auditable, but the negative reason is clearly in the hidden section.
            self.assertIn("PURE_SOFTWARE_BACKEND", text)
            self.assertIn("CAE Engineer", text)
            db.close()


if __name__ == "__main__":
    unittest.main()
