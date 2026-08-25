import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

from src.models import Job
from src.utils import fingerprint, safe_slug, latex_escape
from src.filters import hard_filter, heuristic_score
from src.db import Database
from src.career import detect_job_language, detect_employment_type, detect_german_requirement, load_career_scope, classify_career_family
from src.cv_sources import select_cv_source, combined_cv_text, configured_cv_sources
from src.documents import protect_identity_lines, restore_identity_lines
from src.config import load_config


class CoreTests(unittest.TestCase):
    def test_fingerprint_stable(self):
        self.assertEqual(
            fingerprint("ACME", "Backend Engineer", "Berlin"),
            fingerprint("acme", "backend engineer", "berlin"),
        )

    def test_age_filter(self):
        cfg = {"search": {"max_age_days": 7}, "preferences": {}}
        old = Job(
            "x", "1", "Python Developer", "A", "Berlin", "https://x",
            published_at=datetime.now(timezone.utc) - timedelta(days=10),
        )
        ok, _ = hard_filter(old, cfg)
        self.assertFalse(ok)

    def test_broad_heuristic_engineering(self):
        cfg = load_config("config.yaml")
        profile = __import__("json").loads(Path("input/profile.json").read_text(encoding="utf-8"))
        job = Job(
            "x", "1", "Berechnungsingenieur FEM", "A", "Hamburg", "https://x",
            description="ANSYS FEM Simulation, strukturmechanische Berechnung, Modal- und Schwingungsanalyse",
        )
        self.assertGreaterEqual(heuristic_score(job, profile, cfg), 60)

    def test_db_upsert_dedupe(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(str(Path(td) / "x.db"))
            a = Job("one", "1", "Backend Engineer", "Acme", "Berlin", "https://a")
            b = Job("two", "2", "backend engineer", "ACME", "berlin", "https://b")
            f1 = db.upsert_job(a)
            f2 = db.upsert_job(b)
            self.assertEqual(f1, f2)
            self.assertEqual(db.stats()["total"], 1)
            db.close()

    def test_german_language_detection(self):
        job = Job(
            "x", "1", "Entwicklungsingenieur Maschinenbau (m/w/d)", "A", "Kiel", "https://x",
            description="Ihre Aufgaben sind die Entwicklung und Konstruktion. Wir suchen Erfahrung in der Berechnung und gute Deutschkenntnisse.",
        )
        self.assertEqual(detect_job_language(job), "de")

    def test_english_language_detection(self):
        job = Job(
            "x", "1", "Structural Analysis Engineer", "A", "Berlin", "https://x",
            description="We are looking for an engineer with experience in structural dynamics and simulation. Your responsibilities include analysis and design.",
        )
        self.assertEqual(detect_job_language(job), "en")

    def test_employment_types(self):
        full = Job("x", "1", "Mechanical Engineer", "A", "Berlin", "https://x", description="Unbefristete Vollzeitstelle")
        thesis = Job("x", "2", "Masterarbeit Windenergie", "A", "Berlin", "https://x")
        student = Job("x", "3", "Werkstudent Simulation", "A", "Berlin", "https://x")
        self.assertEqual(detect_employment_type(full), "full_time")
        self.assertEqual(detect_employment_type(thesis), "master_thesis")
        self.assertEqual(detect_employment_type(student), "working_student")

    def test_career_family_classification(self):
        scope = load_career_scope("input/career_scope.yaml")
        job = Job(
            "x", "1", "CAE Engineer Structural Dynamics", "A", "Munich", "https://x",
            description="FEA ANSYS modal vibration harmonic response",
        )
        key, _, tier, score = classify_career_family(job, scope)
        self.assertEqual(key, "cae_structural_dynamics")
        self.assertEqual(tier, "core")
        self.assertGreater(score, 0)

    def test_cv_source_selection_by_language_and_family(self):
        cfg = load_config("config.yaml")
        wind = Job(
            "x", "1", "Wind Turbine Loads Engineer", "A", "Hamburg", "https://x",
            description="OpenFAST offshore wind structural loads",
        )
        src = select_cv_source(wind, cfg, target_language="en", career_family="wind_loads_structures", employment_type="full_time")
        self.assertIsNotNone(src)
        self.assertEqual(src.key, "wind_en")

        de = Job(
            "x", "2", "Berechnungsingenieur FEM", "A", "Hamburg", "https://x",
            description="ANSYS FEM Strukturdynamik Schwingungsanalyse",
        )
        src2 = select_cv_source(de, cfg, target_language="de", career_family="cae_structural_dynamics", employment_type="full_time")
        self.assertIsNotNone(src2)
        self.assertEqual(src2.key, "mechanical_de")

    def test_thesis_specialist_cv_selection(self):
        cfg = load_config("config.yaml")
        job = Job("x", "3", "Master Thesis Wind Turbine Structural Loads", "A", "Hamburg", "https://x", description="OpenFAST ANSYS wind")
        src = select_cv_source(job, cfg, target_language="en", career_family="wind_loads_structures", employment_type="master_thesis")
        self.assertIsNotNone(src)
        self.assertEqual(src.key, "wind_thesis_en")

    def test_evidence_library_has_multiple_cv_families(self):
        cfg = load_config("config.yaml")
        evidence = combined_cv_text(cfg)
        self.assertIn("high-frequency vibrating screen", evidence.lower())
        self.assertIn("rotor-based wind inflow estimation", evidence.lower())
        self.assertGreaterEqual(len(configured_cv_sources(cfg)), 5)

    def test_german_requirement_is_risk_not_hard_filter(self):
        cfg = load_config("config.yaml")
        job = Job("x", "4", "Entwicklungsingenieur", "A", "Kiel", "https://x", description="Vollzeit. Sehr gute Deutschkenntnisse C1 erforderlich. Konstruktion und Entwicklung.")
        self.assertEqual(detect_german_requirement(job), "c1_plus_or_fluent")
        ok, _ = hard_filter(job, cfg)
        self.assertTrue(ok)

    def test_identity_protection_roundtrip(self):
        tex = Path("input/cvs/mechanical_en_master.tex").read_text(encoding="utf-8")
        masked, protected = protect_identity_lines(tex)
        self.assertGreater(len(protected), 4)
        self.assertNotIn("REPLACELINKEDIN", masked)
        self.assertNotIn("REPLACEEMAIL", masked)
        restored, ok = restore_identity_lines(masked, protected)
        self.assertTrue(ok)
        self.assertEqual(restored, tex.rstrip("\n"))


if __name__ == "__main__":
    unittest.main()
