from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import load_config
from src.dashboard import build_dashboard
from src.db import Database
from src.models import Job, MatchResult

OUTPUT = ROOT / "output"
ASSETS = ROOT / "docs" / "assets"


def add_job(db: Database, *, idx: int, title: str, company: str, location: str,
            fit: int | None, priority: int | None, label: str = "",
            source: str = "arbeitnow", career: str = "Mechanical / product development",
            tier: str = "core", lang: str = "en", german: str = "none",
            status: str = "new", filter_reason: str = "", decision: str = "",
            evidence: list[str] | None = None, stage: str = "pre") -> None:
    job = Job(
        source=source,
        source_id=f"demo-{idx}",
        title=title,
        company=company,
        location=location,
        url=f"https://example.org/jobs/{idx}",
        description="Synthetic demo vacancy used only to render the public dashboard screenshot.",
        published_at=datetime.now(timezone.utc) - timedelta(days=idx),
    )
    fp = db.upsert_job(job)
    db.set_active(fp, "active")
    if fit is not None and priority is not None:
        match = MatchResult(
            score=fit,
            recommendation="Strong fit" if fit >= 78 else "Review",
            priority_score=priority,
            priority_label=label,
            priority_reasons=["Strong technical overlap", "Recent vacancy"],
            strong_matches=["mechanical engineering", "simulation", "Python"],
            partial_matches=["domain-specific toolchain"] if fit < 85 else [],
            missing_required=["specialized certification"] if priority < 70 else [],
            risks=["Verify language expectations"] if german != "none" else [],
            reasoning="Synthetic example showing how local fit, practical priority and evidence traceability appear in the review UI.",
            source="heuristic" if stage == "pre" else "codex_cli",
            evaluation_stage=stage,
            evidence_ids=evidence or ["EXP_CAE_001", "SKILL_PY_001"],
            job_language=lang,
            german_requirement=german,
            career_family_label=career,
            career_tier=tier,
            source_cv="mechanical_en",
            technical_fit=min(100, fit + 3),
            experience_fit=max(0, fit - 4),
            language_fit=90 if german in {"none", "preferred"} else 65,
            education_fit=88,
        )
        db.set_match(fp, match)
    if filter_reason:
        db.set_filter_reason(fp, filter_reason)
    else:
        db.set_status(fp, status)
    if decision:
        db.record_feedback(fp, decision, "Synthetic demo decision", career_family="demo")


def main() -> None:
    OUTPUT.mkdir(exist_ok=True)
    ASSETS.mkdir(parents=True, exist_ok=True)
    db_path = OUTPUT / "demo_job_agent.sqlite3"
    if db_path.exists():
        db_path.unlink()

    db = Database(str(db_path))
    try:
        add_job(db, idx=1, title="Structural Analysis Engineer", company="Northwind Mechanics", location="Hamburg, Germany", fit=91, priority=88, label="HIGH", career="CAE / structural dynamics", tier="core", stage="deep")
        add_job(db, idx=2, title="Wind Turbine Loads Engineer", company="BlueRotor Energy", location="Bremen, Germany", fit=87, priority=84, label="HIGH", career="Wind energy engineering", tier="core", stage="deep", evidence=["WIND_OPENFAST_001", "SKILL_PY_001"])
        add_job(db, idx=3, title="Mechanical Design Engineer", company="Vector Works GmbH", location="Berlin, Germany", fit=82, priority=76, label="REVIEW", career="Mechanical / product development", tier="core", decision="SAVE")
        add_job(db, idx=4, title="Simulation Engineer", company="Delta Mobility", location="Munich, Germany", fit=76, priority=69, label="POSSIBLE", career="Simulation / computational engineering", tier="adjacent", german="b2_or_good")
        add_job(db, idx=5, title="Controls & Mechatronics Engineer", company="Kinetic Systems", location="Stuttgart, Germany", fit=72, priority=63, label="POSSIBLE", career="Controls / robotics / mechatronics", tier="adjacent", german="preferred")
        add_job(db, idx=6, title="Backend Platform Engineer", company="Cloud Harbor", location="Remote", fit=None, priority=None, source="arbeitnow", filter_reason="PURE_SOFTWARE_BACKEND")

        (OUTPUT / "discovery_report.json").write_text(json.dumps({
            "automatic_discovery_active": True,
            "raw_results": 146,
            "title_gate_rejected": 51,
            "freshness_filtered": 24,
            "eligible_after_relevance_filters": 31,
            "sources": [
                {"name": "arbeitsagentur", "category": "broad", "operational": True, "success": True, "results": 74},
                {"name": "arbeitnow", "category": "broad", "operational": True, "success": True, "results": 42},
                {"name": "manual", "category": "manual", "operational": True, "success": True, "results": 2},
            ],
        }, indent=2), encoding="utf-8")
        (OUTPUT / "last_run_report.json").write_text(json.dumps({
            "run_mode": "LOCAL_PREVIEW",
            "detail_enrichment_deferred": 19,
            "packages_ready": 0,
            "packages_would_generate": 2,
            "existing_packages_skipped": 3,
            "queued_packages": [],
            "notifications_sent": 0,
            "ai_usage": {"calls": 0, "successful_calls": 0, "failed_calls": 0, "estimated_input_tokens": 0, "operations": {}},
            "stage_seconds": {"discovery": 6.2, "ranking": 0.7, "total_seconds": 7.4},
            "http": {"page_fetches": 18, "cache_hits": 27},
            "ai_budget": {"locked": True, "lock_reason": "Public demo template", "remaining_calls": 0, "usage_hint_percent": 0},
        }, indent=2), encoding="utf-8")
        (OUTPUT / "application_index.json").write_text(json.dumps({
            "application_jobs": 3,
            "companies": 3,
            "missing_artifact_packages": 0,
        }, indent=2), encoding="utf-8")

        cfg = load_config(str(ROOT / "config.yaml"))
        html = build_dashboard(db, output=str(OUTPUT / "demo_dashboard.html"), cfg=cfg)
        print(html)
    finally:
        db.close()


if __name__ == "__main__":
    main()
