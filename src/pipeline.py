from __future__ import annotations
import json
import os
from pathlib import Path

from .models import MatchResult
from .db import Database
from .sources.adzuna import AdzunaSource
from .sources.jooble import JoobleSource
from .sources.greenhouse import GreenhouseSource
from .sources.lever import LeverSource
from .sources.smartrecruiters import SmartRecruitersSource
from .sources.manual import ManualLinksSource
from .sources.email_alert_files import EmailAlertFilesSource
from .pagecheck import check_and_enrich
from .filters import hard_filter
from .ai import AIEngine
from .documents import generate_package
from .notifier import notify
from .search_planner import build_search_queries
from .career import (
    load_career_scope,
    detect_job_language,
    detect_employment_type,
    classify_career_family,
    detect_german_requirement,
)
from .cv_sources import select_cv_source, combined_cv_text


def load_profile(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def build_sources(cfg: dict):
    scfg = cfg.get("sources", {})
    country = cfg.get("search", {}).get("country", "de")
    out = []
    if scfg.get("adzuna", {}).get("enabled", False):
        out.append(AdzunaSource(country))
    if scfg.get("jooble", {}).get("enabled", False):
        out.append(JoobleSource())
    if scfg.get("greenhouse", {}).get("enabled", False):
        out.append(GreenhouseSource(scfg.get("greenhouse", {}).get("boards", [])))
    if scfg.get("lever", {}).get("enabled", False):
        out.append(LeverSource(scfg.get("lever", {}).get("sites", [])))
    if scfg.get("smartrecruiters", {}).get("enabled", False):
        out.append(SmartRecruitersSource(scfg.get("smartrecruiters", {}).get("companies", [])))
    if scfg.get("manual_links", {}).get("enabled", False):
        out.append(ManualLinksSource(scfg.get("manual_links", {}).get("file", "input/manual_jobs.txt")))
    if scfg.get("email_alert_files", {}).get("enabled", False):
        out.append(EmailAlertFilesSource(scfg.get("email_alert_files", {}).get("directory", "input/job_alerts")))
    return out


def _match_from_json(raw: str | None) -> MatchResult | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
        allowed = {k: v for k, v in data.items() if k in MatchResult.__dataclass_fields__}
        return MatchResult(**allowed)
    except Exception:
        return None


def run_pipeline(cfg: dict, db: Database, dry_run: bool = False):
    profile = load_profile(cfg.get("documents", {}).get("profile", "input/profile.json"))
    ai = AIEngine(cfg)
    sources = build_sources(cfg)
    queries = build_search_queries(cfg, profile, ai)
    locations = cfg.get("search", {}).get("locations", []) or [""]
    limit = int(cfg.get("search", {}).get("results_per_source", 25))
    verify = bool(cfg.get("search", {}).get("verify_live_page", True))
    min_score = int(cfg.get("preferences", {}).get("minimum_match_score", 65))
    package_score = int(cfg.get("preferences", {}).get("package_generation_score", 78))
    max_ai = int(cfg.get("ai", {}).get("max_jobs_per_run", 24))
    desktop = bool(cfg.get("notifications", {}).get("desktop", True))
    scope = load_career_scope(cfg.get("search", {}).get("career_scope_file", "input/career_scope.yaml"))
    evidence_bundle = combined_cv_text(cfg)

    found = []
    errors = []
    for src in sources:
        pairs = [("", "")] if src.name in ("manual", "email_alert") else [(q, l) for q in queries for l in locations]
        for q, loc in pairs:
            try:
                found.extend(src.search(q, loc, limit))
            except Exception as e:
                errors.append(f"{src.name}: {e}")

    seen = set()
    unique = []
    for job in found:
        key = (
            job.company.lower().strip(),
            job.title.lower().strip(),
            job.location.lower().strip(),
            job.url.split("?")[0],
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(job)

    processed = 0
    strong = []
    packages = []
    not_ready = []

    for job in unique:
        if verify:
            active, job = check_and_enrich(job)
        else:
            active = "unknown"
        if not job.title:
            job.title = "Unknown job"
        if not job.company:
            job.company = "Unknown company"

        fp = db.upsert_job(job)
        db.set_active(fp, active)
        if active == "expired":
            continue

        ok, _reason = hard_filter(job, cfg)
        if not ok:
            continue

        lang = detect_job_language(job)
        emp = detect_employment_type(job)
        german_req = detect_german_requirement(job)
        family_key, family_label, tier, family_signal = classify_career_family(job, scope)
        source_cv = select_cv_source(
            job, cfg, target_language=lang, career_family=family_key, employment_type=emp
        )
        context = {
            "job_language": lang,
            "employment_type": emp,
            "german_requirement": german_req,
            "career_family": family_key,
            "career_family_label": family_label,
            "career_tier": tier,
            "career_family_signal": family_signal,
            "source_cv": source_cv.key if source_cv else "",
        }

        state = db.get_job_state(fp) or {}
        match = _match_from_json(state.get("match_json"))

        needs_ai_upgrade = bool(match is not None and match.source == "heuristic" and ai.enabled)
        if match is None or needs_ai_upgrade:
            if processed >= max_ai:
                continue
            match = ai.match(job, profile, candidate_cv=evidence_bundle, context=context)
            processed += 1
            db.set_match(fp, match)
        else:
            # Keep classifications current even when reusing a cached score.
            match.job_language = lang
            match.employment_type = emp
            match.career_family = family_key
            match.career_family_label = family_label
            match.career_tier = tier
            match.source_cv = source_cv.key if source_cv else ""
            match.german_requirement = german_req

        if match.score >= min_score:
            strong.append((job, match))

        state = db.get_job_state(fp) or {}
        app_status = state.get("application_status")
        should_generate = (
            match.score >= package_score
            and active != "expired"
            and not dry_run
            and (
                not state.get("has_application", False)
                or (app_status == "needs_ai_or_review" and ai.enabled)
            )
        )
        if should_generate:
            pkg, res = generate_package(job, match, profile, cfg, ai, fp, source_cv)
            status = "package_ready" if res.get("ready") else "needs_ai_or_review"
            db.record_application(fp, str(pkg), status=status)
            if res.get("ready"):
                packages.append((job, match, pkg, res))
                notify(
                    "New application package ready",
                    f"{job.title} at {job.company} — {match.score}% — {lang.upper()} — {emp}. Files: {pkg}",
                    desktop,
                )
            else:
                not_ready.append((job, match, pkg, res))

    return {
        "ai_backend": ai.backend_name(),
        "queries_this_cycle": len(queries),
        "raw_found": len(found),
        "unique": len(unique),
        "evaluated": processed,
        "strong_matches": len(strong),
        "ready_packages": len(packages),
        "packages_needing_ai_or_review": len(not_ready),
        "errors": errors,
        "top": sorted(
            [
                {
                    "title": j.title,
                    "company": j.company,
                    "score": m.score,
                    "language": m.job_language,
                    "employment_type": m.employment_type,
                    "german_requirement": m.german_requirement,
                    "family": m.career_family_label,
                    "tier": m.career_tier,
                    "url": j.url,
                }
                for j, m in strong
            ],
            key=lambda x: x["score"],
            reverse=True,
        )[:15],
    }
