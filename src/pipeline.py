from __future__ import annotations
import json
from pathlib import Path

from .models import MatchResult
from .db import Database
from .sources.adzuna import AdzunaSource
from .sources.arbeitsagentur import ArbeitsagenturSource
from .sources.arbeitnow import ArbeitnowSource
from .sources.jooble import JoobleSource
from .sources.greenhouse import GreenhouseSource
from .sources.lever import LeverSource
from .sources.smartrecruiters import SmartRecruitersSource
from .sources.manual import ManualLinksSource
from .sources.email_alert_files import EmailAlertFilesSource
from .pagecheck import PageChecker
from .filters import hard_filter, age_days, heuristic_score
from .ai import AIEngine
from .documents import generate_package
from .notifier import notify
from .search_planner import build_search_queries
from .career import (
    load_career_scope,
    detect_job_language,
    detect_employment_profile,
    classify_career_family,
    detect_german_requirement,
)
from .cv_sources import select_cv_source
from .evidence import load_evidence_registry, retrieve_evidence, evidence_by_ids
from .priority import calculate_priority
from .feedback import family_feedback_adjustments, write_feedback_summary
from .utils import canonical_url, source_identity, is_safe_http_url


def load_profile(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def build_sources(cfg: dict):
    scfg = cfg.get("sources", {})
    country = cfg.get("search", {}).get("country", "de")
    out = []
    if scfg.get("arbeitsagentur", {}).get("enabled", False): out.append(ArbeitsagenturSource(scfg.get("arbeitsagentur", {})))
    if scfg.get("arbeitnow", {}).get("enabled", False): out.append(ArbeitnowSource(scfg.get("arbeitnow", {})))
    if scfg.get("adzuna", {}).get("enabled", False): out.append(AdzunaSource(country))
    if scfg.get("jooble", {}).get("enabled", False): out.append(JoobleSource())
    if scfg.get("greenhouse", {}).get("enabled", False): out.append(GreenhouseSource(scfg.get("greenhouse", {}).get("boards", [])))
    if scfg.get("lever", {}).get("enabled", False): out.append(LeverSource(scfg.get("lever", {}).get("sites", [])))
    if scfg.get("smartrecruiters", {}).get("enabled", False): out.append(SmartRecruitersSource(scfg.get("smartrecruiters", {}).get("companies", [])))
    if scfg.get("manual_links", {}).get("enabled", False): out.append(ManualLinksSource(scfg.get("manual_links", {}).get("file", "input/manual_jobs.txt")))
    if scfg.get("email_alert_files", {}).get("enabled", False): out.append(EmailAlertFilesSource(scfg.get("email_alert_files", {}).get("directory", "input/job_alerts")))
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


def _evaluate_job(job, profile, context, cfg, ai, registry, screen_count: int, deep_count: int):
    tiered = cfg.get("ai", {}).get("tiered", {}) or {}
    enabled = bool(tiered.get("enabled", True))
    base = heuristic_score(job, profile, cfg)
    screen_limit = int(tiered.get("screen_evidence_limit", 8))
    deep_limit = int(tiered.get("deep_evidence_limit", 16))
    screen_evidence = retrieve_evidence(job, registry, limit=screen_limit, career_family=context["career_family"])
    screen_ids = [str(x.get("id")) for x in screen_evidence if x.get("id")]

    if not ai.enabled:
        return ai.heuristic_match(job, profile, context, screen_ids), screen_count, deep_count

    if not enabled:
        lexical = retrieve_evidence(job, registry, limit=deep_limit, career_family=context["career_family"])
        semantic_ids = ai.select_evidence(job, profile, registry, context, lexical, limit=deep_limit)
        deep_evidence = evidence_by_ids(semantic_ids, registry) or lexical
        return ai.match(job, profile, deep_evidence, context=context, base_score=base), screen_count, deep_count + 1

    screen_min = int(tiered.get("screen_min_pre_score", 40))
    max_screen = int(tiered.get("max_screen_per_run", 24))
    max_deep = int(tiered.get("max_deep_per_run", 10))
    force_manual = bool(tiered.get("manual_force_screen", True)) and job.source == "manual"
    if base < screen_min and not force_manual:
        return ai.heuristic_match(job, profile, context, screen_ids), screen_count, deep_count
    if screen_count >= max_screen:
        m = ai.heuristic_match(job, profile, context, screen_ids)
        m.decision_reasons.append("AI screening budget for this cycle was exhausted; retry on a later run.")
        return m, screen_count, deep_count

    screen = ai.screen(job, profile, screen_evidence, context, base_score=base)
    screen_count += 1
    sscore = int(screen.get("screen_score", base) or base)
    sdecision = str(screen.get("decision", "HOLD")).upper()
    deep_min = int(tiered.get("deep_min_screen_score", 58))
    force_pre = int(tiered.get("deep_force_pre_score", 72))
    promote = sdecision == "PROMOTE" or sscore >= deep_min or base >= force_pre

    if not promote:
        return ai.screen_to_match(job, profile, screen_evidence, context, base, screen), screen_count, deep_count

    if deep_count >= max_deep:
        m = ai.heuristic_match(job, profile, context, screen_ids)
        m.screen_score = sscore
        m.screen_decision = sdecision
        m.decision_reasons.append("Deep AI budget for this cycle was exhausted; job will be retried on a later run.")
        return m, screen_count, deep_count

    lexical_deep = retrieve_evidence(job, registry, limit=deep_limit, career_family=context["career_family"])
    semantic_enabled = bool(cfg.get("evidence", {}).get("semantic_selection", {}).get("enabled", True))
    if semantic_enabled:
        semantic_ids = ai.select_evidence(job, profile, registry, context, lexical_deep, limit=deep_limit)
        deep_evidence = evidence_by_ids(semantic_ids, registry) or lexical_deep
    else:
        deep_evidence = lexical_deep
    match = ai.match(job, profile, deep_evidence, context=context, base_score=base, screen_data=screen)
    deep_count += 1
    return match, screen_count, deep_count


def _document_evidence(job, match: MatchResult, registry: list[dict], cfg: dict) -> list[dict]:
    """Use deep-match citations first, then fill with other relevant verified evidence."""
    limit = int(cfg.get("evidence", {}).get("document_evidence_limit", 18) or 18)
    chosen = evidence_by_ids(match.evidence_ids, registry)
    have = {str(x.get("id")) for x in chosen}
    for item in retrieve_evidence(job, registry, career_family=match.career_family, limit=limit):
        iid = str(item.get("id", ""))
        if iid and iid not in have:
            chosen.append(item); have.add(iid)
        if len(chosen) >= limit:
            break
    return chosen[:limit]


def _source_queries(queries: list[str], src_name: str, source_cfg: dict) -> list[str]:
    """Keep a small anchor set every cycle and rotate the remaining queries per source."""
    cap = int(source_cfg.get("max_queries_per_run", 0) or 0)
    if cap <= 0 or cap >= len(queries):
        return list(queries)
    anchor_count = min(int(source_cfg.get("anchor_queries_per_run", max(2, cap // 2)) or 0), cap, len(queries))
    anchors = list(queries[:anchor_count])
    pool = list(queries[anchor_count:])
    slots = cap - len(anchors)
    if slots <= 0 or not pool:
        return anchors[:cap]
    state_path = Path("output/source_query_rotation.json")
    state = {}
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        state = {}
    start = int((state.get(src_name) or {}).get("next_index", 0) or 0) % len(pool)
    rotated = [pool[(start + i) % len(pool)] for i in range(slots)]
    state[src_name] = {"next_index": (start + slots) % len(pool)}
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return anchors + rotated


def _write_discovery_report(report: dict, path: str = "output/discovery_report.json") -> None:
    p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def run_pipeline(cfg: dict, db: Database, dry_run: bool = False):
    profile = load_profile(cfg.get("documents", {}).get("profile", "input/profile.json"))
    db.configure_telemetry(cfg)
    ai = AIEngine(cfg, usage_recorder=db.record_usage)
    sources = build_sources(cfg)
    queries = build_search_queries(cfg, profile, ai)
    locations = cfg.get("search", {}).get("locations", []) or [""]
    limit = int(cfg.get("search", {}).get("results_per_source", 25))
    verify = bool(cfg.get("search", {}).get("verify_live_page", True))
    page_checker = PageChecker(cfg) if verify else None
    min_score = int(cfg.get("preferences", {}).get("minimum_match_score", 63))
    package_priority = int(cfg.get("priority", {}).get("package_generation_min", 74))
    immediate_priority = int(cfg.get("notifications", {}).get("immediate_priority_min", 82))
    desktop = bool(cfg.get("notifications", {}).get("desktop", True))
    scope = load_career_scope(cfg.get("search", {}).get("career_scope_file", "input/career_scope.yaml"))
    registry = load_evidence_registry(cfg)
    feedback_adjustments = family_feedback_adjustments(db, cfg)

    found, errors = [], []
    source_reports = []
    source_cfg_all = cfg.get("sources", {}) or {}
    for src in sources:
        health = src.health() if hasattr(src, "health") else {"name": src.name, "category": "unknown", "automatic": True, "configured": True, "operational": True, "reason": "ready"}
        rep = dict(health)
        rep.update({"attempted": False, "success": False, "queries_used": 0, "results": 0, "error": ""})
        if not health.get("operational", True):
            source_reports.append(rep)
            continue
        sc = source_cfg_all.get(src.name, {}) or {}
        src_limit = int(sc.get("results_per_query", limit) or limit)
        try:
            rep["attempted"] = True
            if src.name in ("manual", "email_alert"):
                src_results = src.search("", "", src_limit)
                rep["queries_used"] = 0
            else:
                qset = _source_queries(queries, src.name, sc)
                rep["queries_used"] = len(qset)
                src_results = src.search_many(qset, locations, src_limit)
            found.extend(src_results)
            rep["results"] = len(src_results)
            rep["success"] = True
        except Exception as exc:
            rep["error"] = str(exc)
            errors.append(f"{src.name}: {exc}")
        source_reports.append(rep)

    broad_success = [x for x in source_reports if x.get("category") == "broad" and x.get("automatic") and x.get("success")]
    auto_discovery_active = bool(broad_success)
    discovery_report = {
        "version": "1.7",
        "automatic_discovery_active": auto_discovery_active,
        "planned_queries": len(queries),
        "sources": source_reports,
        "raw_results": len(found),
        "warning": "" if auto_discovery_active else "AUTOMATIC JOB SEARCH IS NOT ACTIVE: no broad discovery source completed successfully.",
    }
    _write_discovery_report(discovery_report)

    seen, unique = set(), []
    for job in found:
        if not is_safe_http_url(job.url):
            errors.append(f"{job.source}: rejected unsafe/non-HTTP job URL: {job.url}")
            continue
        key = canonical_url(job.url) or source_identity(job)
        if key in seen:
            continue
        seen.add(key); unique.append(job)

    # Phase 1: enrich/filter/classify every vacancy cheaply. This means AI budget is
    # spent on the strongest candidates, not simply whichever source happened to run first.
    candidates = []
    parse_failures = []
    for job in unique:
        # Do not download obviously stale automatically-discovered detail pages.
        # Manual URLs intentionally bypass this freshness shortcut.
        pre_age = age_days(job)
        max_age = cfg.get("search", {}).get("max_age_days", 7)
        if job.source != "manual" and pre_age is not None and pre_age > max_age:
            fp = db.upsert_job(job)
            db.set_active(fp, "unknown")
            db.set_filter_reason(fp, f"older than {max_age} days")
            continue
        if verify:
            active, job = page_checker.check_and_enrich(job)
        else:
            active = "unknown"
        bad_title = not job.title or job.title.strip().lower() in {"job", "unknown job", "careers", "job details"}
        bad_company = not job.company or job.company.strip().lower() in {"unknown company", "jobs", "careers"}
        if bad_title and bad_company:
            parse_failures.append({"url": job.url, "active": active, "reason": "Could not extract job title/company"})
            continue
        if not job.title: job.title = "Job (title not parsed)"
        if not job.company: job.company = "Company not parsed"

        fp = db.upsert_job(job)
        db.set_active(fp, active)
        if active == "expired":
            continue
        ok, filter_reason = hard_filter(job, cfg)
        if not ok:
            db.set_filter_reason(fp, filter_reason)
            continue
        db.set_filter_reason(fp, "")

        lang = detect_job_language(job)
        employment = detect_employment_profile(job)
        emp = employment["primary"]
        german_req = detect_german_requirement(job)
        family_key, family_label, tier, family_signal = classify_career_family(job, scope)
        source_cv = select_cv_source(job, cfg, target_language=lang, career_family=family_key, employment_type=emp)
        context = {
            "job_language": lang,
            "employment_type": emp,
            "career_stage": employment["career_stage"],
            "schedule": employment["schedule"],
            "contract": employment["contract"],
            "german_requirement": german_req,
            "career_family": family_key,
            "career_family_label": family_label,
            "career_tier": tier,
            "career_family_signal": family_signal,
            "career_family_options": [
                {"id": k, "label": str(v.get("label", k)), "tier": str(v.get("tier", "adjacent"))}
                for k, v in (scope.get("families", {}) or {}).items()
            ],
            "source_cv": source_cv.key if source_cv else "",
        }
        base = heuristic_score(job, profile, cfg)
        # Manual links receive a small ordering bonus because the user explicitly chose
        # them, but their actual FIT score remains unchanged.
        ordering_score = base + (8 if job.source == "manual" else 0)
        candidates.append({
            "job": job, "fp": fp, "active": active, "context": context,
            "source_cv": source_cv, "base": base, "ordering_score": ordering_score,
        })

    candidates.sort(key=lambda x: (x["ordering_score"], x["base"]), reverse=True)

    screened = 0
    deep_evaluated = 0
    evaluated = 0
    strong, packages, not_ready = [], [], []

    # Phase 2: tiered AI, in ranked order.
    for c in candidates:
        job, fp, active, context, source_cv = c["job"], c["fp"], c["active"], c["context"], c["source_cv"]
        state = db.get_job_state(fp) or {}
        match = _match_from_json(state.get("match_json"))
        # Deep AI and HOLD/SKIP screens are cached. Cheap heuristic rows are refreshed
        # so parser fixes/new Codex availability can upgrade them automatically.
        should_refresh = match is None or match.source == "heuristic" or match.analysis_version != "1.6"
        if should_refresh:
            match, screened, deep_evaluated = _evaluate_job(
                job, profile, context, cfg, ai, registry, screened, deep_evaluated
            )
            evaluated += 1
            a = age_days(job)
            max_age = cfg.get("search", {}).get("max_age_days", 7)
            if job.source == "manual" and a is not None and a > max_age:
                warning = f"Vacancy is about {int(a)} days old, but it was evaluated because you supplied the URL manually."
                if warning not in match.risks:
                    match.risks.append(warning)
        else:
            match.job_language = context["job_language"]
            match.employment_type = context["employment_type"]
            match.career_stage = context["career_stage"]
            match.schedule = context["schedule"]
            match.contract = context["contract"]
            match.career_family = context["career_family"]
            match.career_family_label = context["career_family_label"]
            match.career_tier = context["career_tier"]
            match.source_cv = context["source_cv"]
            match.german_requirement = context["german_requirement"]

        adjustment = feedback_adjustments.get(context["career_family"], 0.0)
        pscore, plabel, preasons = calculate_priority(job, match, cfg, feedback_adjustment=adjustment)
        match.priority_score = pscore
        match.priority_label = plabel
        match.priority_reasons = preasons
        practical_action = {"HIGH":"APPLY", "REVIEW":"REVIEW", "LOW":"SAVE_OR_SKIP", "REJECT":"REJECT"}.get(plabel, "REVIEW")
        match.decision = practical_action
        for reason in preasons:
            if reason not in match.decision_reasons:
                match.decision_reasons.append(reason)
        db.set_match(fp, match)

        if match.score >= min_score:
            strong.append((job, match))

        state = db.get_job_state(fp) or {}
        user_decision = str(state.get("user_decision", "") or "").upper()
        app_status = state.get("application_status")
        deep_match = match.source in {"codex_cli", "openai_api"}
        legacy_package_needs_audit = False
        if state.get("has_application", False) and state.get("package_dir"):
            audit_required = bool(cfg.get("evidence", {}).get("semantic_audit", {}).get("required_for_ready", True))
            if audit_required:
                try:
                    status_path = Path(str(state.get("package_dir"))) / "package_status.json"
                    pdata = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else {}
                    legacy_package_needs_audit = not bool(pdata.get("semantic_evidence_audit_ok"))
                except Exception:
                    legacy_package_needs_audit = True
        should_generate = (
            deep_match
            and match.priority_score >= package_priority
            and active != "expired"
            and user_decision not in {"SKIP", "NOT_INTERESTED"}
            and not dry_run
            and (not state.get("has_application", False) or (app_status == "needs_ai_or_review" and ai.enabled) or legacy_package_needs_audit)
        )
        if should_generate:
            doc_evidence = _document_evidence(job, match, registry, cfg)
            pkg, res = generate_package(job, match, profile, cfg, ai, fp, source_cv, evidence_items=doc_evidence)
            status = "package_ready" if res.get("ready") else "needs_ai_or_review"
            db.record_application(fp, str(pkg), status=status)
            if res.get("ready"):
                packages.append((job, match, pkg, res))
                if match.priority_score >= immediate_priority:
                    notify(
                        "High-priority application ready",
                        f"{job.title} at {job.company} — Fit {match.score}, Priority {match.priority_score} ({match.priority_label}). Files: {pkg}",
                        desktop,
                    )
            else:
                not_ready.append((job, match, pkg, res))

    write_feedback_summary(db, cfg)
    return {
        "ai_backend": ai.backend_name(),
        "queries_this_cycle": len(queries),
        "automatic_discovery_active": auto_discovery_active,
        "discovery_warning": discovery_report.get("warning", ""),
        "source_report": source_reports,
        "discovery_report": "output/discovery_report.json",
        "raw_found": len(found),
        "unique": len(unique),
        "eligible_after_filters": len(candidates),
        "evaluated": evaluated,
        "ai_screened": screened,
        "deep_ai_evaluated": deep_evaluated,
        "strong_matches": len(strong),
        "ready_packages": len(packages),
        "packages_needing_ai_or_review": len(not_ready),
        "errors": errors,
        "parse_failures": parse_failures,
        "usage_today": db.usage_stats(1),
        "top": sorted([
            {
                "title": j.title,
                "company": j.company,
                "fit": m.score,
                "priority": m.priority_score,
                "priority_label": m.priority_label,
                "source": m.source,
                "language": m.job_language,
                "employment_type": m.employment_type,
                "german_requirement": m.german_requirement,
                "family": m.career_family_label,
                "tier": m.career_tier,
                "url": j.url,
            }
            for j, m in strong
        ], key=lambda x: (x["priority"], x["fit"]), reverse=True)[:15],
    }
