from __future__ import annotations
from .models import Job, MatchResult
from .filters import age_days


def heuristic_language_fit(german_requirement: str, job_language: str = "en") -> int:
    if german_requirement in ("none", ""):
        return 90 if job_language == "de" else 100
    return {
        "preferred": 78,
        "b1_or_basic": 92,
        "b2_or_good": 58,
        "c1_plus_or_fluent": 35,
        "required_unspecified": 62,
    }.get(german_requirement, 65)


def _practicality(job: Job, match: MatchResult, cfg: dict) -> tuple[int, list[str]]:
    score, reasons = 100, []
    if match.german_requirement == "c1_plus_or_fluent" and match.language_fit < 70:
        score -= 22; reasons.append("Major German-language gap")
    elif match.german_requirement == "b2_or_good" and match.language_fit < 70:
        score -= 12; reasons.append("German level below requested B2/good level")
    elif match.german_requirement == "required_unspecified" and match.language_fit < 70:
        score -= 8; reasons.append("German required; exact level unclear")
    elif match.german_requirement == "preferred" and match.language_fit < 70:
        score -= 2; reasons.append("German is preferred, not mandatory")

    if match.missing_required:
        score -= min(28, len(match.missing_required) * 8)
        reasons.append(f"{len(match.missing_required)} missing/uncertain required item(s)")
    if match.career_tier == "stretch":
        score -= 8; reasons.append("Stretch career family")
    elif match.career_tier == "adjacent":
        score -= 3; reasons.append("Adjacent career family")
    if match.career_stage in {"senior", "lead", "principal", "director"}:
        score -= 15; reasons.append("Seniority may be above target")
    if match.schedule == "full_time" and match.career_stage == "professional":
        score += 4; reasons.append("Professional full-time target")
    elif match.employment_type == "internship":
        score -= 2

    a = age_days(job)
    max_age = int(cfg.get("search", {}).get("max_age_days", 7) or 7)
    if job.source == "manual" and a is not None and a > max_age:
        score -= min(6, max(2, int(a // 14)))
        reasons.append("Older manually supplied vacancy")

    loc = (job.location or "").lower()
    preferred_locations = [str(x).lower() for x in cfg.get("preferences", {}).get("preferred_locations", [])]
    if loc and preferred_locations and not any(x in loc for x in ("germany", "deutschland", "remote")):
        # Only a light penalty: the location parser may return a city without the country.
        if not any(x in loc for x in preferred_locations):
            score -= 5; reasons.append("Location may be outside preferred area")
    if match.recommendation.upper() == "SKIP":
        score -= 10; reasons.append("AI fit evaluator recommended SKIP")
    return max(0, min(100, score)), reasons


def calculate_priority(
    job: Job,
    match: MatchResult,
    cfg: dict,
    feedback_adjustment: float = 0.0,
) -> tuple[int, str, list[str]]:
    """Return practical application priority, deliberately separate from FIT."""
    fit = max(0, min(100, int(match.score or 0)))
    if match.language_fit <= 0:
        match.language_fit = heuristic_language_fit(match.german_requirement, match.job_language)
    practicality, reasons = _practicality(job, match, cfg)

    # FIT dominates; practical constraints and language modify attention priority rather
    # than rewriting the evidence-fit score itself.
    priority = round(fit * 0.78 + match.language_fit * 0.07 + practicality * 0.15)
    adj = float(feedback_adjustment or 0.0)
    if adj:
        priority = round(priority + adj)
        reasons.append(f"Learned career-family preference adjustment {adj:+.1f}")
    priority = max(0, min(100, priority))

    pcfg = cfg.get("priority", {}) or {}
    high = int(pcfg.get("high_min", 82))
    review = int(pcfg.get("review_min", 68))
    low = int(pcfg.get("low_min", 55))
    if priority >= high:
        label = "HIGH"
    elif priority >= review:
        label = "REVIEW"
    elif priority >= low:
        label = "LOW"
    else:
        label = "REJECT"
    if not reasons:
        reasons.append("No major practical blocker detected")
    return priority, label, reasons


def compute_priority(job: Job, match: MatchResult, cfg: dict, db=None) -> MatchResult:
    """Compatibility helper used by older callers/tests."""
    adjustment = 0.0
    if db is not None and match.career_family:
        try:
            fcfg = cfg.get("feedback", {}) or {}
            summary = db.feedback_family_summary(match.career_family)
            n = int(summary.get("preference_samples", 0) or 0)
            min_samples = int(fcfg.get("min_samples_for_adjustment", 5) or 5)
            if n >= min_samples:
                max_adj = float(fcfg.get("max_priority_adjustment", 8) or 8)
                adjustment = max(-max_adj, min(max_adj, float(summary.get("preference_value", 0.0) or 0.0) * 4.0))
        except Exception:
            adjustment = 0.0
    p, label, reasons = calculate_priority(job, match, cfg, adjustment)
    match.priority_score = p
    match.priority_label = label
    match.priority_reasons = reasons
    merged = list(match.decision_reasons or [])
    for reason in reasons:
        if reason not in merged:
            merged.append(reason)
    match.decision_reasons = merged
    match.decision = "APPLY" if label == "HIGH" else ("REVIEW" if label == "REVIEW" else ("SAVE_OR_SKIP" if label == "LOW" else "REJECT"))
    return match

# Backward-compatible public helper used by tests and external scripts.
def feedback_adjustment(db, career_family: str, minimum_samples: int = 5, maximum_adjustment: int = 8) -> tuple[int, str]:
    if db is None or not career_family:
        return 0, ""
    try:
        summary = db.feedback_family_summary(career_family)
    except Exception:
        return 0, ""
    n = int(summary.get("preference_samples", 0) or 0)
    if n < int(minimum_samples):
        return 0, ""
    value = float(summary.get("preference_value", 0.0) or 0.0)
    lim = max(0, int(maximum_adjustment))
    adj = round(max(-float(lim), min(float(lim), value * 4.0)))
    return (adj, f"Learned preference adjustment {adj:+d} from {n} prior decision(s) in this career family") if adj else (0, "")
