from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.config import load_config
from src.pipeline import build_sources, _source_queries
from src.sources.arbeitsagentur import ArbeitsagenturSource
from src.sources.arbeitnow import ArbeitnowSource


class V17DiscoveryTests(unittest.TestCase):
    def test_default_config_has_real_broad_sources(self):
        cfg = load_config("config.yaml")
        sources = build_sources(cfg)
        health = {s.name: s.health() for s in sources}
        self.assertTrue(health["arbeitsagentur"]["operational"])
        self.assertTrue(health["arbeitnow"]["operational"])
        self.assertEqual(health["arbeitsagentur"]["category"], "broad")
        self.assertEqual(health["arbeitnow"]["category"], "broad")
        self.assertFalse(health["adzuna"]["operational"] if "adzuna" in health else True)

    def test_ba_search_html_parser(self):
        html = """<html><body><ul><li>
        <a href='/jobsuche/jobdetail/12265-243426_JB5210654-S'>1. Ergebnis: Berechnungsingenieur (m/w/d)</a>
        <h4>Arbeitgeber: FERCHAU GmbH Niederlassung Ulm</h4>
        <div>Arbeitsort: Ulm, Donau Anstellungsart: Vollzeit Veröffentlichungsdatum: Vor 3 Tagen veröffentlicht</div>
        </li></ul></body></html>"""
        src = ArbeitsagenturSource({"max_queries_per_run": 12})
        jobs = src._parse(html, 10)
        self.assertEqual(len(jobs), 1)
        j = jobs[0]
        self.assertEqual(j.title, "Berechnungsingenieur (m/w/d)")
        self.assertEqual(j.company, "FERCHAU GmbH Niederlassung Ulm")
        self.assertEqual(j.location, "Ulm, Donau")
        self.assertIn("12265-243426", j.url)
        self.assertIsNotNone(j.published_at)

    def test_ba_student_query_uses_student_offer_type(self):
        self.assertEqual(ArbeitsagenturSource._angebot_for("Werkstudent Windenergie"), 34)
        self.assertEqual(ArbeitsagenturSource._angebot_for("Masterarbeit Windenergie"), 34)
        self.assertEqual(ArbeitsagenturSource._angebot_for("Berechnungsingenieur"), 1)

    def test_arbeitnow_fetches_catalogue_once_for_many_queries(self):
        payload = {"data": [
            {"slug":"wind-1","title":"Wind Energy Engineer","company_name":"ACME Wind","location":"Hamburg, Germany",
             "url":"https://www.arbeitnow.com/jobs/acme-wind-1","description":"OpenFAST wind turbine simulation", "tags":["wind"], "job_types":["full-time"], "created_at":"2026-08-14T08:00:00Z"},
            {"slug":"fr-1","title":"Software Engineer","company_name":"FR Co","location":"Paris, France",
             "url":"https://www.arbeitnow.com/jobs/fr-1","description":"software", "tags":[], "job_types":[], "created_at":"2026-08-14T08:00:00Z"},
        ], "meta":{"last_page":1}}
        response = Mock(); response.raise_for_status = Mock(); response.json.return_value = payload
        with patch("src.sources.arbeitnow.requests.get", return_value=response) as get:
            src = ArbeitnowSource({"pages":3,"max_results_per_run":120})
            jobs = src.search_many(["wind energy engineer","CAE engineer"],["Germany"],25)
        self.assertEqual(get.call_count, 1)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].company, "ACME Wind")

    def test_per_source_query_rotation_keeps_anchor_and_caps(self):
        queries = [f"q{i}" for i in range(20)]
        with tempfile.TemporaryDirectory() as td:
            old = Path.cwd()
            try:
                import os
                os.chdir(td)
                first = _source_queries(queries, "x", {"max_queries_per_run": 8, "anchor_queries_per_run": 4})
                second = _source_queries(queries, "x", {"max_queries_per_run": 8, "anchor_queries_per_run": 4})
            finally:
                os.chdir(old)
        self.assertEqual(first[:4], queries[:4])
        self.assertEqual(second[:4], queries[:4])
        self.assertEqual(len(first), 8)
        self.assertNotEqual(first[4:], second[4:])


if __name__ == "__main__":
    unittest.main()
