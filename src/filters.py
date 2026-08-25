from __future__ import annotations
from datetime import datetime, timezone
from .models import Job
from .utils import normalize_text
from .career import detect_employment_type, load_career_scope, classify_career_family
from .relevance import assess_relevance, title_relevance_gate, specific_profile_hits


def age_days(job: Job) -> float | None:
    if not job.published_at:
        return None
    dt = job.published_at
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).total_seconds() / 86400


def freshness_limits(cfg: dict) -> dict[str, int]:
    """Return the staged automatic-discovery freshness policy.

    V1.8.1 replaces the former seven-day hard cutoff with tiers:
      * 0..full_eligibility_days: fully eligible
      * up to active_grace_days: eligible when still live (pipeline verifies)
      * up to strong_title_max_days: only strong target titles may survive when live
      * beyond that: automatic jobs are filtered

    `max_age_days` remains a backwards-compatible fallback for old configs.
    """
    scfg = cfg.get("search", {}) or {}
    legacy = int(scfg.get("max_age_days", 30) or 30)
    fresh = int(scfg.get("fresh_days", 7) or 7)
    full = int(scfg.get("full_eligibility_days", max(fresh, 14)) or max(fresh, 14))
    grace = int(scfg.get("active_grace_days", max(full, legacy)) or max(full, legacy))
    strong = int(scfg.get("strong_title_max_days", max(grace, 45)) or max(grace, 45))
    fresh = max(0, fresh)
    full = max(fresh, full)
    grace = max(full, grace)
    strong = max(grace, strong)
    return {"fresh": fresh, "full": full, "grace": grace, "strong": strong}


def freshness_bucket(job: Job, cfg: dict) -> str:
    """Classify vacancy age without deciding live-page status."""
    a = age_days(job)
    if a is None:
        return "unknown"
    lim = freshness_limits(cfg)
    if a <= lim["fresh"]:
        return "fresh"
    if a <= lim["full"]:
        return "recent"
    if a <= lim["grace"]:
        return "active_grace"
    if a <= lim["strong"]:
        return "strong_title_grace"
    return "too_old"


def hard_filter(job: Job, cfg: dict) -> tuple[bool, str]:
    title = normalize_text(job.title)
    prefs = cfg.get("preferences", {})
    for bad in prefs.get("excluded_title_keywords", []) or []:
        if normalize_text(bad) in title:
            return False, f"excluded title keyword: {bad}"
    required = prefs.get("required_title_keywords", []) or []
    if required and not any(normalize_text(x) in title for x in required):
        return False, "missing required title keyword"

    # Freshness is deliberately no longer a seven-day hard cutoff. The pipeline checks
    # live status for grace-period jobs before this function is called. Here we only
    # reject jobs beyond the automatic policy's maximum, or 31-45 day jobs that do not
    # have a strong target title. Manual URLs retain the explicit bypass behavior.
    manual_cfg = cfg.get("sources", {}).get("manual_links", {}) or {}
    bypass_manual_age = bool(manual_cfg.get("bypass_age_filter", True))
    bucket = freshness_bucket(job, cfg)
    if not (job.source == "manual" and bypass_manual_age):
        if bucket == "too_old":
            lim = freshness_limits(cfg)
            return False, f"older than {lim['strong']} days"
        if bucket == "strong_title_grace":
            gate = title_relevance_gate(job, cfg)
            if gate.title_strength != "strong":
                lim = freshness_limits(cfg)
                return False, f"older than {lim['grace']} days without strong target title"

    relevance = assess_relevance(job, cfg)
    if not relevance.keep:
        return False, relevance.reason

    typ = detect_employment_type(job)
    allowed = set(prefs.get("allowed_employment_types", []) or [])
    # "professional" means the vacancy did not expose a reliable schedule/contract
    # label. It must not be rejected merely because the ATS omitted "full time".
    if allowed and typ not in allowed:
        professional_is_allowed = typ == "professional" and ("professional" in allowed or "full_time" in allowed)
        if not professional_is_allowed:
            return False, f"employment type not enabled: {typ}"
    return True, "ok"


def _profile_terms(profile: dict) -> list[str]:
    terms: list[str] = []
    for s in profile.get("skills", []) or []:
        if isinstance(s, str):
            terms.append(s)
        elif isinstance(s, dict):
            terms.extend(str(k) for k in s.keys())
    caps = profile.get("transferable_capabilities", {}) or {}
    for _, values in caps.items():
        if isinstance(values, list):
            terms.extend(str(v) for v in values)
    return terms


def heuristic_score(job: Job, profile: dict, cfg: dict) -> int:
    """Domain-anchored local PRE score.

    V1.8+ deliberately gives almost no value to generic words such as engineer,
    development, project or automation. A vacancy needs a real mechanical/CAE/wind/
    simulation/manufacturing/controls bridge before it can obtain a useful PRE score.
    """
    relevance = assess_relevance(job, cfg)
    if not relevance.keep:
        return 0

    preferred = cfg.get("preferences", {}).get("preferred_keywords", []) or []
    profile_terms = _profile_terms(profile) + list(preferred)
    evidence_hits = specific_profile_hits(job, profile_terms)

    if relevance.title_strength == "strong":
        score = 48
    elif relevance.title_strength == "bridge":
        score = 36
    elif relevance.title_strength == "body":
        score = 28
    else:
        score = 16

    score += min(14, len(relevance.title_anchor_hits) * 5)
    score += min(12, len(relevance.title_bridge_hits) * 3)
    score += min(16, len(relevance.body_domain_hits) * 2)
    score += min(18, len(evidence_hits) * 3)

    scope_path = cfg.get("search", {}).get("career_scope_file", "input/career_scope.yaml")
    scope = load_career_scope(scope_path)
    _, _, tier, family_signal = classify_career_family(job, scope)
    if family_signal > 0:
        tier_bonus = {"core": 10, "adjacent": 7, "stretch": 4}.get(tier, 5)
        score += min(tier_bonus, 2 + family_signal)

    title = normalize_text(job.title)
    if relevance.title_strength in {"strong", "bridge"} and any(x in title for x in ("werkstudent", "working student", "praktikum", "internship", "masterarbeit", "master thesis")):
        score += 5

    return int(max(0, min(100, score)))
