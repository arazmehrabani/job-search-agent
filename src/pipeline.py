from __future__ import annotations
import json
import time
import hashlib
import copy
from datetime import datetime, timezone
from pathlib import Path

from .models import Job, MatchResult
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
from .filters import hard_filter, age_days, heuristic_score, freshness_bucket, freshness_limits
from .relevance import title_relevance_gate, assess_relevance
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
from .utils import canonical_url, source_identity, is_safe_http_url, parse_datetime


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


def _analysis_input_hash(job: Job) -> str:
    payload = "\n".join([
        str(job.title or "").strip(),
        str(job.company or "").strip(),
        str(job.location or "").strip(),
        " ".join(str(job.description or "").split()),
    ])
    return hashlib.sha256(payload.encode("utf-8", errors="replace")).hexdigest()[:24]


def _notify_once(db: Database, fp: str, kind: str, title: str, message: str, desktop: bool) -> bool:
    if db.notification_sent(fp, kind):
        return False
    if notify(title, message, desktop):
        db.record_notification(fp, kind)
        return True
    return False


def _ai_remaining_calls(ai) -> int:
    fn = getattr(ai, "budget_remaining_calls", None)
    if callable(fn):
        try:
            return int(fn())
        except Exception:
            return 0
    return 10**9 if getattr(ai, "enabled", False) else 0


def _ai_budget_snapshot(ai) -> dict:
    fn = getattr(ai, "budget_snapshot", None)
    if callable(fn):
        try:
            return dict(fn() or {})
        except Exception:
            return {}
    return {"locked": not bool(getattr(ai, "enabled", False)), "remaining_calls": _ai_remaining_calls(ai), "compatibility_stub": True}


def _apply_rolling_ai_budget(cfg: dict, db: Database, ai: AIEngine) -> dict:
    """Secondary DB-backed usage guard/report.

    The AIEngine also owns a cross-project ledger, which is the stronger protection.
    This DB guard counts *all provider attempts* (not only successes) and aligns its
    longer window with the manually recorded allowance-period start when available.
    """
    bcfg = (cfg.get("ai", {}) or {}).get("budget", {}) or {}
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

    period_start = ""
    try:
        hint_path = Path(str(bcfg.get("usage_hint_file", "input/codex_usage_hint.json") or "input/codex_usage_hint.json")).expanduser()
        if hint_path.exists():
            hint = json.loads(hint_path.read_text(encoding="utf-8"))
            raw = str(hint.get("period_started_on", "") or "").strip()
            if raw:
                period_start = datetime.fromisoformat(raw + "T00:00:00+00:00").isoformat()
    except Exception:
        period_start = ""
    if not period_start:
        period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()

    day = db.usage_since(day_start)
    period = db.usage_since(period_start)
    max_day = max(0, int(bcfg.get("max_provider_calls_per_day", bcfg.get("max_successful_calls_per_day", 4)) or 0))
    max_period = max(0, int(bcfg.get("max_provider_calls_per_allowance_period", bcfg.get("max_successful_calls_per_calendar_month", 12)) or 0))
    if ai.enabled and max_day and int(day.get("calls", 0) or 0) >= max_day:
        if hasattr(ai, "force_budget_lock"):
            ai.force_budget_lock(f"Project DB daily provider-call ceiling reached ({day.get('calls',0)}/{max_day} attempts today).")
    if ai.enabled and max_period and int(period.get("calls", 0) or 0) >= max_period:
        if hasattr(ai, "force_budget_lock"):
            ai.force_budget_lock(f"Project DB allowance-period provider-call ceiling reached ({period.get('calls',0)}/{max_period} attempts).")
    return {
        "daily": day, "allowance_period": period, "allowance_period_started_at": period_start,
        "max_provider_calls_per_day": max_day,
        "max_provider_calls_per_allowance_period": max_period,
        "note": "Counts provider attempts, including failures; cross-project ledger in AIEngine is the primary guard.",
    }


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


def _write_application_index(db: Database, path: str = "output/application_index.json") -> dict:
    rows = []
    companies = set()
    missing_artifacts = 0
    for r in db.application_rows():
        company = str(r["company"] or "")
        if company: companies.add(company)
        package_dir = str(r["package_dir"] or "")
        artifact_exists = bool(package_dir and Path(package_dir).exists())
        if not artifact_exists:
            missing_artifacts += 1
        rows.append({
            "fingerprint": str(r["job_fingerprint"] or ""),
            "title": str(r["title"] or ""),
            "company": company,
            "status": str(r["status"] or ""),
            "package_dir": package_dir,
            "artifact_exists": artifact_exists,
            "fit": r["match_score"], "priority": r["priority_score"],
            "url": str(r["url"] or ""), "created_at": str(r["created_at"] or ""), "updated_at": str(r["updated_at"] or ""),
        })
    obj = {"application_jobs": len(rows), "companies": len(companies), "missing_artifact_packages": missing_artifacts, "packages": rows}
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding="utf-8")
    return obj


def _usage_delta(before: dict, after: dict) -> dict:
    keys = ("calls", "input_tokens", "output_tokens", "successful_calls", "estimated_cost_usd")
    out = {}
    for key in keys:
        a = after.get(key, 0) or 0
        b = before.get(key, 0) or 0
        out[key] = max(0, a - b)
    return out


def _operation_usage_map(rows: list[dict]) -> dict[str, dict]:
    return {str(r.get("operation", "")): dict(r) for r in rows}


def _operation_usage_delta(before_rows: list[dict], after_rows: list[dict]) -> list[dict]:
    before = _operation_usage_map(before_rows)
    after = _operation_usage_map(after_rows)
    out = []
    for op in sorted(after):
        a = after[op]; b = before.get(op, {})
        row = {"operation": op}
        for key in ("calls", "input_tokens", "output_tokens", "successful_calls"):
            row[key] = max(0, int(a.get(key, 0) or 0) - int(b.get(key, 0) or 0))
        if row["calls"] or row["input_tokens"] or row["output_tokens"]:
            out.append(row)
    return out


def _write_last_run_report(report: dict, path: str = "output/last_run_report.json") -> None:
    p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def run_pipeline(cfg: dict, db: Database, dry_run: bool = False):
    # DRY RUN now means genuinely local/no-Codex. It is a safety preview, not an
    # expensive matching run with documents suppressed.
    if dry_run:
        cfg = copy.deepcopy(cfg)
        cfg.setdefault("ai", {}).setdefault("budget", {})["manual_pause"] = True
    run_started = time.perf_counter()
    stage_marks = {}
    profile = load_profile(cfg.get("documents", {}).get("profile", "input/profile.json"))
    db.configure_telemetry(cfg)
    ai = AIEngine(cfg, usage_recorder=db.record_usage)
    if dry_run:
        # Safety invariant: LOCAL_PREVIEW is zero-provider even if a future/fake AIEngine
        # ignores the budget.manual_pause configuration.
        ai.enabled = False
    rolling_budget = _apply_rolling_ai_budget(cfg, db, ai)
    sources = build_sources(cfg)
    queries = build_search_queries(cfg, profile, ai)
    locations = cfg.get("search", {}).get("locations", []) or [""]
    limit = int(cfg.get("search", {}).get("results_per_source", 25))
    verify = bool(cfg.get("search", {}).get("verify_live_page", True))
    page_checker = PageChecker(cfg) if verify else None
    min_score = int(cfg.get("preferences", {}).get("minimum_match_score", 63))
    package_priority = int(cfg.get("priority", {}).get("package_generation_min", 74))
    immediate_priority = int(cfg.get("notifications", {}).get("immediate_priority_min", 82))
    local_pre_notify = int(cfg.get("notifications", {}).get("local_candidate_pre_min", 76) or 76)
    desktop = bool(cfg.get("notifications", {}).get("desktop", True))
    scope = load_career_scope(cfg.get("search", {}).get("career_scope_file", "input/career_scope.yaml"))
    registry = load_evidence_registry(cfg)
    feedback_adjustments = family_feedback_adjustments(db, cfg)
    usage_before = db.usage_stats()
    usage_ops_before = db.usage_by_operation()

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

    stage_marks["discovery_seconds"] = round(time.perf_counter() - run_started, 3)
    broad_success = [x for x in source_reports if x.get("category") == "broad" and x.get("automatic") and x.get("success")]
    auto_discovery_active = bool(broad_success)
    discovery_report = {
        "version": "1.9.0",
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
    title_gate_rejected = 0
    post_enrichment_rejected = 0
    freshness_filtered = 0
    limits = freshness_limits(cfg)
    detail_cfg = (cfg.get("http", {}) or {}).get("detail_enrichment", {}) or {}
    detail_soft_max = max(0, int(detail_cfg.get("max_network_detail_checks_per_run", 45) or 0))
    detail_hard_max = max(detail_soft_max, int(detail_cfg.get("hard_max_with_strong_titles", 60) or 0))
    full_desc_chars = max(0, int(detail_cfg.get("skip_fresh_if_description_chars_at_least", 500) or 0))
    detail_checks_used = 0
    detail_deferred = 0
    detail_skipped_full_description = 0

    # Put strong target titles first before spending detail-page requests. The same-host
    # throttle remains untouched; V1.9 saves time by making fewer requests, not faster ones.
    def _cheap_enrichment_rank(j):
        gate = title_relevance_gate(j, cfg)
        strength = {"strong":3,"medium":2,"weak":1}.get(str(gate.title_strength),0)
        bucket0 = freshness_bucket(j, cfg)
        fresh = {"fresh":5,"recent":4,"unknown":3,"active_grace":2,"strong_title_grace":1}.get(bucket0,0)
        return (1 if j.source=="manual" else 0, strength, fresh)
    unique.sort(key=_cheap_enrichment_rank, reverse=True)

    for job in unique:
        # Cheap domain rejection comes first, even for old jobs. There is no reason to
        # spend a detail-page request on an obviously unrelated backend/sales/HR role.
        title_gate = title_relevance_gate(job, cfg)
        if not title_gate.keep:
            fp = db.upsert_job(job)
            db.set_active(fp, "unknown")
            db.set_filter_reason(fp, title_gate.reason)
            title_gate_rejected += 1
            continue

        # If a discovery source already supplied a meaningful full description (for
        # example Arbeitnow), use that text for the post-title relevance gate BEFORE
        # making another HTTP request. This safely saves page checks for clearly
        # unrelated jobs without imposing a hard enrichment cap on good vacancies.
        if len((job.description or "").strip()) >= 160 and job.source != "manual":
            pre_page_relevance = assess_relevance(job, cfg)
            if not pre_page_relevance.keep:
                fp = db.upsert_job(job)
                db.set_active(fp, "unknown")
                db.set_filter_reason(fp, pre_page_relevance.reason)
                post_enrichment_rejected += 1
                continue

        # V1.8.1 staged freshness policy: 0-14 days remain fully eligible; 15-30 day
        # jobs may continue if the detail page confirms they are live; 31-45 day jobs
        # get one last chance only for strong target titles. Manual URLs still bypass.
        bucket = freshness_bucket(job, cfg)
        if job.source != "manual":
            if bucket == "too_old":
                fp = db.upsert_job(job)
                db.set_active(fp, "unknown")
                db.set_filter_reason(fp, f"older than {limits['strong']} days")
                freshness_filtered += 1
                continue
            if bucket == "strong_title_grace" and title_gate.title_strength != "strong":
                fp = db.upsert_job(job)
                db.set_active(fp, "unknown")
                db.set_filter_reason(fp, f"older than {limits['grace']} days without strong target title")
                freshness_filtered += 1
                continue

        if verify:
            has_full_discovery_text = len((job.description or "").strip()) >= full_desc_chars > 0
            can_skip_fresh_detail = has_full_discovery_text and bucket in {"fresh", "recent", "unknown"} and job.source != "manual"
            if can_skip_fresh_detail:
                active = "unknown"
                detail_skipped_full_description += 1
            else:
                strong_or_manual = title_gate.title_strength == "strong" or job.source == "manual"
                cap = detail_hard_max if strong_or_manual else detail_soft_max
                if detail_checks_used >= cap:
                    fp = db.upsert_job(job)
                    db.set_active(fp, "unknown")
                    db.set_status(fp, "discovered_unenriched")
                    detail_deferred += 1
                    continue
                active, job = page_checker.check_and_enrich(job)
                detail_checks_used += 1
        else:
            active = "unknown"

        if job.source != "manual" and bucket in {"active_grace", "strong_title_grace"} and active != "active":
            fp = db.upsert_job(job)
            db.set_active(fp, active)
            db.set_filter_reason(fp, f"{int(age_days(job) or 0)}-day-old vacancy; live status not confirmed")
            freshness_filtered += 1
            continue
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
            if filter_reason in {"NO_RELEVANT_ENGINEERING_DOMAIN_SIGNAL"} or filter_reason in {
                "PURE_SOFTWARE_BACKEND", "BUSINESS_SALES_MARKETING", "FINANCE_HR_ADMIN", "DESIGN_MEDIA_NONENGINEERING", "SOFTWARE_PRODUCT_DESIGN"
            }:
                post_enrichment_rejected += 1
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
        relevance = assess_relevance(job, cfg)
        # Relevance rank comes before PRE score. This guarantees that a CAE/mechanical/
        # wind/simulation vacancy reaches limited AI budgets before generic or weak
        # adjacent titles returned earlier by a source. Manual links get a small bonus.
        freshness_rank = {"fresh": 5, "recent": 4, "unknown": 3, "active_grace": 2, "strong_title_grace": 1}.get(bucket, 0)
        ordering_score = relevance.rank * 2 + freshness_rank * 8 + base + (10 if job.source == "manual" else 0)
        candidates.append({
            "job": job, "fp": fp, "active": active, "context": context,
            "source_cv": source_cv, "base": base, "relevance_rank": relevance.rank,
            "freshness_rank": freshness_rank, "ordering_score": ordering_score,
        })

    # Within the same relevance tier, fresher vacancies receive scarce Codex budget first.
    candidates.sort(key=lambda x: (x["relevance_rank"], x["freshness_rank"], x["base"], x["ordering_score"]), reverse=True)

    discovery_report.update({
        "unique_results": len(unique),
        "title_gate_rejected": title_gate_rejected,
        "post_enrichment_rejected": post_enrichment_rejected,
        "freshness_filtered": freshness_filtered,
        "eligible_after_relevance_filters": len(candidates),
        "detail_page_checks_used": detail_checks_used,
        "detail_enrichment_deferred": detail_deferred,
        "detail_checks_skipped_full_description": detail_skipped_full_description,
    })
    _write_discovery_report(discovery_report)
    stage_marks["enrichment_filtering_seconds"] = round(time.perf_counter() - run_started - stage_marks.get("discovery_seconds", 0.0), 3)

    # V1.9 execution policy: local ranking first, no routine AI screen, no routine
    # semantic evidence-selection call. Codex is reserved for a small number of direct
    # deep evaluations and for NEW application packages only.
    screened = 0
    deep_evaluated = 0
    evaluated = 0
    strong, packages, not_ready = [], [], []
    package_errors = []
    would_generate = []
    queued_packages = []
    notifications_sent = 0
    existing_packages_skipped = 0

    strategy = cfg.get("ai", {}).get("strategy", {}) or {}
    max_new_deep = max(0, int(strategy.get("max_new_deep_per_run", 2) or 0))
    deep_min_pre = int(strategy.get("deep_min_pre_score", 63) or 63)
    deep_min_local_priority = int(strategy.get("deep_min_local_priority", 68) or 68)
    skip_c1_gap = bool(strategy.get("skip_deep_if_german_c1_gap", True))
    deep_limit = int(strategy.get("deep_evidence_limit", 14) or 14)
    reserve_doc_calls = max(0, int(strategy.get("reserve_calls_for_new_packages", 2) or 0))
    reuse_completed = bool(strategy.get("reuse_completed_deep", True))
    reuse_legacy = bool(strategy.get("reuse_legacy_deep", True))
    refresh_changed = bool(strategy.get("refresh_if_job_description_changed", True))
    max_new_packages = max(0, int(strategy.get("max_new_packages_per_run", 2) or 0))

    _local_rank_started = time.perf_counter()
    work = []
    deep_pool = []
    for c in candidates:
        job, fp, context = c["job"], c["fp"], c["context"]
        state = db.get_job_state(fp) or {}
        cached = _match_from_json(state.get("match_json"))
        current_hash = _analysis_input_hash(job)
        item = dict(c)
        item["state_before"] = state
        item["analysis_input_hash"] = current_hash
        item["needs_deep"] = False
        item["deep_rank"] = -1.0

        reusable = False
        if cached is not None and cached.source in {"codex_cli", "openai_api"} and cached.evaluation_stage == "deep" and not cached.deep_pending:
            if state.get("has_application"):
                # An existing application is immutable during normal search. Preserve the
                # deep analysis that justified it; do not refresh it merely because a
                # career page changed wording. Explicit repair is document-only.
                reusable = True
            elif cached.analysis_input_hash:
                reusable = bool(reuse_completed and (not refresh_changed or cached.analysis_input_hash == current_hash))
            else:
                # Completed V1.8.x deep analyses are valuable and expensive. Reuse them
                # by default instead of refreshing the whole historical database merely
                # because the software version changed.
                reusable = bool(reuse_completed and reuse_legacy)

        if reusable:
            match = cached
        else:
            evidence = retrieve_evidence(job, registry, limit=deep_limit, career_family=context["career_family"])
            ids = [str(x.get("id")) for x in evidence if x.get("id")]
            match = ai.heuristic_match(job, profile, context, ids)
            match.analysis_version = "1.9.0"
            match.analysis_input_hash = current_hash
            match.deep_pending = False
            user_decision = str(state.get("user_decision", "") or "").upper()
            force_manual = job.source == "manual"
            terminal_decision = user_decision in {"SKIP", "NOT_INTERESTED", "APPLIED", "INTERVIEW", "REJECTED", "OFFER"}

            # Calculate a cheap practical priority before allocating scarce Codex calls.
            # This prevents high technical PRE scores with obvious practical blockers
            # (for example explicit C1 German vs verified B1) from consuming deep slots.
            local_pscore, _, _ = calculate_priority(job, match, cfg, feedback_adjustment=feedback_adjustments.get(context["career_family"], 0.0))
            item["local_priority_score"] = int(local_pscore)
            explicit_c1_gap = context.get("german_requirement") == "c1_plus_or_fluent"
            actionable = bool(local_pscore >= deep_min_local_priority)

            # Existing application packages are immutable during normal search runs.
            # Do not spend a deep-refresh call on them even if the vacancy text changed.
            # Explicit repair mode handles document regeneration separately.
            has_package = bool(state.get("has_application"))
            deserves_deep = bool(
                not has_package and not terminal_decision
                and (c["base"] >= deep_min_pre or force_manual or user_decision == "APPLY")
                and (actionable or force_manual or user_decision == "APPLY")
                and (not (skip_c1_gap and explicit_c1_gap) or force_manual or user_decision == "APPLY")
            )
            if deserves_deep:
                match.deep_pending = True
                item["needs_deep"] = True
                tier_bonus = {"core": 28, "adjacent": 12, "stretch": 0}.get(str(context.get("career_tier", "adjacent")), 6)
                decision_bonus = 28 if user_decision == "APPLY" else 0
                item["deep_rank"] = (
                    float(local_pscore) * 2.2
                    + float(c["base"]) * 1.1
                    + float(c["relevance_rank"]) * 0.35
                    + float(c["freshness_rank"]) * 4.0
                    + tier_bonus + decision_bonus
                    + (20 if force_manual else 0)
                )
                deep_pool.append(item)
            elif (c["base"] >= deep_min_pre and not has_package and not terminal_decision):
                match.deep_pending = True
                if skip_c1_gap and explicit_c1_gap and user_decision != "APPLY":
                    match.decision_reasons.append("Deep Codex review skipped locally because the vacancy explicitly requires C1+/fluent German while verified German is B1; mark Interested to override.")
                elif not actionable and user_decision != "APPLY":
                    match.decision_reasons.append(f"Deep Codex review skipped locally because practical pre-priority {local_pscore} is below the configured deep threshold {deep_min_local_priority}; mark Interested to override.")
        item["match"] = match
        work.append(item)
        evaluated += 1

    stage_marks["local_ranking_seconds"] = round(time.perf_counter() - _local_rank_started, 3)
    stage_marks["screening_seconds"] = 0.0

    # Reserve calls for actual application documents. If the local usage hint has locked
    # Codex (for example because only a few percent of the monthly allowance remain),
    # AIEngine.enabled is false and the run becomes discovery/local-ranking only.
    deep_pool.sort(key=lambda x: (x.get("deep_rank", -1), x.get("ordering_score", 0)), reverse=True)
    remaining_after_reserve = max(0, _ai_remaining_calls(ai) - reserve_doc_calls) if ai.enabled else 0
    deep_slots = min(max_new_deep, remaining_after_reserve)
    selected_deep = {x["fp"] for x in deep_pool[:deep_slots]}
    deep_candidates_local = len(deep_pool)
    deep_selected_planned = len(selected_deep)
    deep_deferred = max(0, deep_candidates_local - deep_selected_planned)

    _deep_started = time.perf_counter()
    for item in work:
        if not item.get("needs_deep"):
            continue
        if item["fp"] not in selected_deep:
            note = "Local ranking marked this job for deep review, but the resource-governed deep budget deferred it to a later run."
            if note not in item["match"].decision_reasons:
                item["match"].decision_reasons.append(note)
            item["match"].deep_pending = True
            continue
        job, context = item["job"], item["context"]
        deep_evidence = retrieve_evidence(job, registry, limit=deep_limit, career_family=context["career_family"])
        deep_match = ai.match(job, profile, deep_evidence, context=context, base_score=item["base"], screen_data={})
        if deep_match.source in {"codex_cli", "openai_api"} and deep_match.evaluation_stage == "deep":
            deep_match.analysis_version = "1.9.0"
            deep_match.analysis_input_hash = item["analysis_input_hash"]
            deep_match.analyzed_at = datetime.now(timezone.utc).isoformat()
            deep_match.deep_pending = False
            deep_evaluated += 1
        else:
            deep_match.analysis_version = "1.9.0"
            deep_match.analysis_input_hash = item["analysis_input_hash"]
            deep_match.deep_pending = True
            note = "Deep AI was unavailable, failed, or was blocked by the local usage budget; local PRE assessment retained."
            if note not in deep_match.decision_reasons:
                deep_match.decision_reasons.append(note)
        item["match"] = deep_match

    stage_marks["deep_matching_seconds"] = round(time.perf_counter() - _deep_started, 3)
    _phase3_started = time.perf_counter()

    # Phase 3a: compute/persist final practical priority for every job first. Documents are
    # generated only after the whole queue is ranked, so package calls go to the best NEW
    # opportunities rather than whichever job happened to be iterated first.
    package_queue = []
    for item in work:
        job, fp, active, context, source_cv = item["job"], item["fp"], item["active"], item["context"], item["source_cv"]
        match = item["match"]
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
        completed_deep = match.source in {"codex_cli", "openai_api"} and match.evaluation_stage == "deep" and not match.deep_pending
        if not completed_deep and plabel == "HIGH":
            high_min = int(cfg.get("priority", {}).get("high_min", 82))
            pscore = min(pscore, max(0, high_min - 1));plabel = "REVIEW"
            pending_reason = "Final HIGH/APPLY status requires a completed deep AI assessment."
            if pending_reason not in preasons:preasons.append(pending_reason)
            match.deep_pending = True

        match.priority_score = pscore;match.priority_label = plabel;match.priority_reasons = preasons
        match.decision = {"HIGH":"APPLY", "REVIEW":"REVIEW", "LOW":"SAVE_OR_SKIP", "REJECT":"REJECT"}.get(plabel, "REVIEW")
        for reason in preasons:
            if reason not in match.decision_reasons:match.decision_reasons.append(reason)
        db.set_match(fp, match)
        if match.score >= min_score:strong.append((job, match))

        state = db.get_job_state(fp) or {}
        user_decision = str(state.get("user_decision", "") or "").upper()
        if (not completed_deep and match.deep_pending and match.score >= local_pre_notify
                and active != "expired" and user_decision not in {"SKIP","NOT_INTERESTED"}
                and not state.get("has_application", False)):
            if _notify_once(
                db, fp, "strong_local_candidate", "Strong job candidate awaiting deep review",
                f"{job.title} at {job.company} — local PRE {match.score}, Priority {match.priority_score}. "
                "Codex deep analysis was deferred by the resource budget; review it in the dashboard.",
                desktop and not dry_run,
            ):
                notifications_sent += 1
        package_eligible = bool(
            completed_deep and match.priority_score >= package_priority and active != "expired"
            and user_decision not in {"SKIP", "NOT_INTERESTED"}
        )
        if not package_eligible:
            continue
        if state.get("has_application", False):
            # Normal search NEVER regenerates an existing package. Explicit repair mode is
            # the only place where an existing package can be rebuilt. If a user copied
            # only the DB to a new project folder and forgot the application artifacts,
            # surface that safely instead of silently spending AI to recreate them.
            existing_packages_skipped += 1
            package_dir = str(state.get("package_dir", "") or "")
            if package_dir and not Path(package_dir).exists() and not dry_run:
                if _notify_once(
                    db, fp, "package_artifacts_missing", "Existing application files are missing",
                    f"{job.title} at {job.company} has an application record, but its package folder is not present here. Copy output/applications from the previous version or use explicit repair mode later.",
                    desktop,
                ):
                    notifications_sent += 1
            continue
        package_queue.append({"item":item,"job":job,"fp":fp,"match":match,"source_cv":source_cv})

    package_queue.sort(key=lambda x: (x["match"].priority_score, x["match"].score, x["item"].get("freshness_rank",0)), reverse=True)
    if dry_run:
        for x in package_queue[:max_new_packages]:
            would_generate.append({"fingerprint":x["fp"],"title":x["job"].title,"company":x["job"].company,"fit":x["match"].score,"priority":x["match"].priority_score})
    else:
        package_slots = min(max_new_packages, _ai_remaining_calls(ai) if ai.enabled else 0)
        selected_packages = package_queue[:package_slots]
        queued_packages = [
            {"fingerprint":x["fp"],"title":x["job"].title,"company":x["job"].company,"fit":x["match"].score,"priority":x["match"].priority_score,"reason":"new-package AI budget/cap exhausted"}
            for x in package_queue[package_slots:]
        ]
        for x in selected_packages:
            item,job,fp,match,source_cv=x["item"],x["job"],x["fp"],x["match"],x["source_cv"]
            doc_evidence = _document_evidence(job, match, registry, cfg)
            try:
                pkg, res = generate_package(job, match, profile, cfg, ai, fp, source_cv, evidence_items=doc_evidence, audit_evidence_items=registry)
            except Exception as exc:
                err={"fingerprint":fp,"title":job.title,"company":job.company,"fit":match.score,"priority":match.priority_score,"error_type":type(exc).__name__,"error":str(exc),"timestamp":datetime.now(timezone.utc).isoformat()}
                package_errors.append(err)
                ep=Path("output/package_errors")/datetime.now().strftime("%Y-%m-%d")/f"{fp}.json";ep.parent.mkdir(parents=True,exist_ok=True);ep.write_text(json.dumps(err,ensure_ascii=False,indent=2),encoding="utf-8")
                if match.priority_score >= immediate_priority and _notify_once(db,fp,"package_error","High-priority package generation failed",f"{job.title} at {job.company}. Error record: {ep}",desktop):notifications_sent += 1
                continue
            status="package_ready" if res.get("ready") else "needs_ai_or_review";db.record_application(fp,str(pkg),status=status)
            if res.get("ready"):
                packages.append((job,match,pkg,res))
                if match.priority_score >= immediate_priority and _notify_once(db,fp,"package_ready","High-priority application ready",f"{job.title} at {job.company} — Fit {match.score}, Priority {match.priority_score}. Files: {pkg}",desktop):notifications_sent += 1
            else:
                not_ready.append((job,match,pkg,res))
                if match.priority_score >= immediate_priority and _notify_once(db,fp,"package_review","High-priority job needs package review",f"{job.title} at {job.company} — package created but not READY. Review: {pkg}",desktop):notifications_sent += 1

        # High-priority new jobs that could not receive a package because the local AI
        # budget was intentionally exhausted are still surfaced once, so resource control
        # cannot make the user miss an important opportunity.
        for q in queued_packages:
            if int(q.get("priority",0) or 0) >= immediate_priority:
                if _notify_once(db,q["fingerprint"],"package_queued","High-priority job queued",f"{q['title']} at {q['company']} is high priority, but the local Codex budget preserved your allowance. Package generation is queued for a later run.",desktop):notifications_sent += 1

    stage_marks["priority_documents_notifications_seconds"] = round(time.perf_counter() - _phase3_started, 3)
    stage_marks["total_seconds"] = round(time.perf_counter() - run_started, 3)
    http_stats = page_checker.policy.stats() if page_checker is not None and hasattr(page_checker.policy, "stats") else {}

    application_index = _write_application_index(db)
    write_feedback_summary(db, cfg)
    usage_after = db.usage_stats()
    usage_ops_after = db.usage_by_operation()
    usage_this_run = _usage_delta(usage_before, usage_after)
    usage_ops_this_run = _operation_usage_delta(usage_ops_before, usage_ops_after)
    resource_plan = {
        "max_new_deep_per_run": max_new_deep,
        "deep_candidates_local": deep_candidates_local,
        "deep_selected_planned": deep_selected_planned,
        "deep_deferred": deep_deferred,
        "reserve_calls_for_new_packages": reserve_doc_calls,
        "max_new_packages_per_run": max_new_packages,
        "new_package_candidates": len(package_queue),
        "hard_max_calls_per_run": _ai_budget_snapshot(ai).get("max_calls_per_run"),
        "hard_max_estimated_input_tokens_per_run": _ai_budget_snapshot(ai).get("max_estimated_input_tokens_per_run"),
    }
    last_run_report = {
        "version": "1.9.0",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "ai_backend": ai.backend_name(),
        "dry_run": bool(dry_run),
        "usage_this_run": usage_this_run,
        "usage_by_operation_this_run": usage_ops_this_run,
        "raw_found": len(found),
        "unique": len(unique),
        "title_gate_rejected": title_gate_rejected,
        "post_enrichment_rejected": post_enrichment_rejected,
        "freshness_filtered": freshness_filtered,
        "eligible_after_filters": len(candidates),
        "detail_page_checks_used": detail_checks_used,
        "detail_enrichment_deferred": detail_deferred,
        "detail_checks_skipped_full_description": detail_skipped_full_description,
        "ai_screened": screened,
        "deep_ai_evaluated": deep_evaluated,
        "ai_strategy": "LOCAL_RANKING_THEN_DEEP",
        "resource_plan": resource_plan,
        "ai_budget": _ai_budget_snapshot(ai),
        "rolling_ai_budget": rolling_budget,
        "existing_packages_skipped": existing_packages_skipped,
        "queued_new_packages": queued_packages,
        "execution_mode": "LOCAL_PREVIEW" if dry_run else "FULL_APPLICATION_PREP",
        "document_generation_enabled": not bool(dry_run),
        "notifications_enabled": bool((not dry_run) and desktop),
        "packages_would_generate": len(would_generate),
        "package_candidates": would_generate[:25],
        "packages_ready": len(packages),
        "packages_needing_review": len(not_ready),
        "package_generation_errors": len(package_errors),
        "package_error_details": package_errors[:25],
        "notifications_sent": notifications_sent,
        "application_index": application_index,
        "stage_seconds": stage_marks,
        "http": http_stats,
        "token_counts_note": "Estimated from text length for Codex CLI; not official OpenAI account usage or billing data.",
    }
    _write_last_run_report(last_run_report)

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
        "detail_page_checks_used": detail_checks_used,
        "detail_enrichment_deferred": detail_deferred,
        "detail_checks_skipped_full_description": detail_skipped_full_description,
        "title_gate_rejected": title_gate_rejected,
        "post_enrichment_rejected": post_enrichment_rejected,
        "freshness_filtered": freshness_filtered,
        "evaluated": evaluated,
        "ai_screened": screened,
        "deep_ai_evaluated": deep_evaluated,
        "ai_strategy": "LOCAL_RANKING_THEN_DEEP",
        "resource_plan": resource_plan,
        "ai_budget": _ai_budget_snapshot(ai),
        "rolling_ai_budget": rolling_budget,
        "existing_packages_skipped": existing_packages_skipped,
        "queued_new_packages": queued_packages,
        "strong_matches": len(strong),
        "ready_packages": len(packages),
        "packages_needing_ai_or_review": len(not_ready),
        "package_generation_errors": len(package_errors),
        "packages_would_generate": len(would_generate),
        "package_candidates": would_generate[:25],
        "notifications_sent": notifications_sent,
        "application_index": application_index,
        "execution_mode": "LOCAL_PREVIEW" if dry_run else "FULL_APPLICATION_PREP",
        "stage_seconds": stage_marks,
        "http": http_stats,
        "errors": errors,
        "parse_failures": parse_failures,
        "usage_this_run": usage_this_run,
        "usage_by_operation_this_run": usage_ops_this_run,
        "usage_today": db.usage_stats(1),
        "last_run_report": "output/last_run_report.json",
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

def resume_application_packages(cfg: dict, db: Database, repair_existing: bool = False) -> dict:
    """Generate documents only from already completed deep matches in the database.

    This recovery mode performs no discovery, page fetching, screening, semantic
    evidence selection for job matching, or deep job matching.  It is intended after
    an interrupted/crashed FULL_APPLICATION_PREP run so expensive completed matching
    work can be reused.  Document tailoring, cover-letter generation and semantic
    claim audit still use the configured AI backend because those are part of creating
    the package itself.
    """
    started = time.perf_counter()
    profile = load_profile(cfg.get("documents", {}).get("profile", "input/profile.json"))
    db.configure_telemetry(cfg)
    ai = AIEngine(cfg, usage_recorder=db.record_usage)
    rolling_budget = _apply_rolling_ai_budget(cfg, db, ai)
    registry = load_evidence_registry(cfg)
    package_priority = int(cfg.get("priority", {}).get("package_generation_min", 74))
    immediate_priority = int(cfg.get("notifications", {}).get("immediate_priority_min", 82))
    desktop = bool(cfg.get("notifications", {}).get("desktop", True))
    usage_before = db.usage_stats(); ops_before = db.usage_by_operation()
    ready = []; needs_review = []; errors = []; skipped_existing = 0; eligible = 0; notifications_sent = 0
    strategy = cfg.get("ai", {}).get("strategy", {}) or {}
    max_packages = max(0, int(strategy.get("max_repair_packages_per_run" if repair_existing else "max_new_packages_per_run", 2) or 0))
    budget_deferred = []
    existing_application_index = _write_application_index(db)

    # Never overwrite a package with fallback/plain content merely because the official
    # Codex allowance is nearly exhausted or the local safety lock is active.
    if not ai.enabled:
        mode = "REPAIR_EXISTING_PACKAGES" if repair_existing else "RESUME_PACKAGES_ONLY"
        report = {
            "version":"1.9.0","mode":mode,"completed_at":datetime.now(timezone.utc).isoformat(),
            "ai_backend":ai.backend_name(),"ai_budget":_ai_budget_snapshot(ai),"rolling_ai_budget":rolling_budget,"eligible_cached_deep_matches":0,
            "skipped_existing_packages":0,"packages_ready":0,"packages_needing_review":0,
            "package_generation_errors":0,"notifications_sent":0,"usage_this_resume":_usage_delta(usage_before, db.usage_stats()),
            "usage_by_operation_this_resume":[],"ready":[],"needs_review":[],"errors":[],"budget_deferred":[],"application_index":existing_application_index,
            "duration_seconds":round(time.perf_counter()-started,3),
            "note":"Document generation did not run because AI/Codex is unavailable or locally budget-locked. Existing packages were left untouched."
        }
        rp=Path("output/resume_packages_report.json");rp.parent.mkdir(parents=True,exist_ok=True);rp.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        Path("output/last_run_report.json").write_text(json.dumps({
            "version":"1.9.0","completed_at":report["completed_at"],"ai_backend":ai.backend_name(),"ai_budget":_ai_budget_snapshot(ai),"rolling_ai_budget":rolling_budget,
            "execution_mode":mode,"document_generation_enabled":False,"notifications_enabled":False,
            "usage_this_run":report["usage_this_resume"],"usage_by_operation_this_run":[],"packages_ready":0,
            "packages_needing_ai_or_review":0,"packages_would_generate":0,"package_generation_errors":0,
            "notifications_sent":0,"stage_seconds":{"document_recovery_seconds":report["duration_seconds"],"total_seconds":report["duration_seconds"]},
            "http":{"page_fetches":0,"cache_hits":0,"network_requests":0,"retries":0,"errors":0,"throttle_sleep_seconds":0.0}
        },ensure_ascii=False,indent=2),encoding="utf-8")
        return report

    for row in db.top_jobs(5000):
        match = _match_from_json(row["match_json"])
        if match is None:
            continue
        deep_match = match.source in {"codex_cli", "openai_api"} and match.evaluation_stage == "deep" and not match.deep_pending
        if not deep_match or int(match.priority_score or row["priority_score"] or 0) < package_priority:
            continue
        if str(row["active_status"] or "").lower() == "expired":
            continue
        fp = str(row["fingerprint"])
        state = db.get_job_state(fp) or {}
        if str(state.get("user_decision", "") or "").upper() in {"SKIP", "NOT_INTERESTED"}:
            continue
        if state.get("has_application"):
            app_status = str(state.get("application_status", "") or "")
            if app_status == "package_ready" or not repair_existing:
                skipped_existing += 1
                continue
        if eligible >= max_packages or _ai_remaining_calls(ai) <= 0:
            budget_deferred.append({"fingerprint":fp,"title":str(row["title"] or ""),"company":str(row["company"] or ""),"reason":"repair/resume package cap or AI budget exhausted"})
            continue
        eligible += 1
        job = Job(
            source=str(row["source"] or ""), source_id=str(row["source_id"] or ""),
            title=str(row["title"] or ""), company=str(row["company"] or ""),
            location=str(row["location"] or ""), url=str(row["url"] or ""),
            apply_url=str(row["apply_url"] or ""), description=str(row["description"] or ""),
            published_at=parse_datetime(row["published_at"]), salary_min=row["salary_min"],
            salary_max=row["salary_max"], currency=str(row["currency"] or "EUR"),
        )
        source_cv = select_cv_source(
            job, cfg, target_language=match.job_language, career_family=match.career_family,
            employment_type=match.employment_type,
        )
        doc_evidence = _document_evidence(job, match, registry, cfg)
        try:
            pkg, res = generate_package(job, match, profile, cfg, ai, fp, source_cv, evidence_items=doc_evidence, audit_evidence_items=registry)
        except Exception as exc:
            err = {
                "fingerprint": fp, "title": job.title, "company": job.company,
                "error_type": type(exc).__name__, "error": str(exc),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            errors.append(err)
            ep = Path("output/package_errors") / datetime.now().strftime("%Y-%m-%d") / f"{fp}.json"
            ep.parent.mkdir(parents=True, exist_ok=True)
            ep.write_text(json.dumps(err, ensure_ascii=False, indent=2), encoding="utf-8")
            if match.priority_score >= immediate_priority:
                if notify("High-priority package generation failed", f"{job.title} at {job.company}. Error record: {ep}", desktop):
                    notifications_sent += 1
            continue
        status = "package_ready" if res.get("ready") else "needs_ai_or_review"
        db.record_application(fp, str(pkg), status=status)
        if res.get("ready"):
            ready.append({"fingerprint": fp, "title": job.title, "company": job.company, "package_dir": str(pkg)})
            if match.priority_score >= immediate_priority:
                if notify("High-priority application ready", f"{job.title} at {job.company}. Files: {pkg}", desktop):
                    notifications_sent += 1
        else:
            needs_review.append({"fingerprint": fp, "title": job.title, "company": job.company, "package_dir": str(pkg), "notes": res.get("notes", [])})
            if match.priority_score >= immediate_priority:
                if notify("High-priority job needs package review", f"{job.title} at {job.company}. Review: {pkg}", desktop):
                    notifications_sent += 1

    application_index = _write_application_index(db)
    usage_after = db.usage_stats(); ops_after = db.usage_by_operation()
    usage_delta = _usage_delta(usage_before, usage_after)
    ops_delta = _operation_usage_delta(ops_before, ops_after)
    duration = round(time.perf_counter() - started, 3)
    mode = "REPAIR_EXISTING_PACKAGES" if repair_existing else "RESUME_PACKAGES_ONLY"
    report = {
        "version": "1.9.0", "mode": mode,
        "completed_at": datetime.now(timezone.utc).isoformat(), "ai_backend": ai.backend_name(),
        "ai_budget": _ai_budget_snapshot(ai), "rolling_ai_budget": rolling_budget,
        "eligible_cached_deep_matches": eligible, "skipped_existing_packages": skipped_existing,
        "budget_deferred": budget_deferred,
        "packages_ready": len(ready), "packages_needing_review": len(needs_review),
        "package_generation_errors": len(errors), "notifications_sent": notifications_sent,
        "application_index": application_index,
        "usage_this_resume": usage_delta, "usage_by_operation_this_resume": ops_delta,
        "ready": ready, "needs_review": needs_review, "errors": errors,
        "duration_seconds": duration,
        "note": "No discovery/job screening/deep job matching was performed; only application documents were generated from cached deep matches.",
    }
    rp = Path("output/resume_packages_report.json"); rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    # Keep the dashboard's single 'last run' view correct after recovery/repair mode.
    last = {
        "version": "1.9.0", "completed_at": report["completed_at"], "ai_backend": ai.backend_name(),
        "ai_budget": _ai_budget_snapshot(ai), "rolling_ai_budget": rolling_budget, "execution_mode": mode, "document_generation_enabled": True, "notifications_enabled": True,
        "usage_this_run": usage_delta, "usage_by_operation_this_run": ops_delta,
        "packages_ready": len(ready), "packages_needing_ai_or_review": len(needs_review),
        "packages_would_generate": 0, "package_generation_errors": len(errors),
        "notifications_sent": notifications_sent,
        "stage_seconds": {"document_recovery_seconds": duration, "total_seconds": duration},
        "http": {"page_fetches": 0, "cache_hits": 0, "network_requests": 0, "retries": 0, "errors": 0, "throttle_sleep_seconds": 0.0},
    }
    Path("output/last_run_report.json").write_text(json.dumps(last, ensure_ascii=False, indent=2), encoding="utf-8")
    return report

