from __future__ import annotations
from datetime import datetime, timezone
from .models import Job
from .utils import normalize_text
from .career import detect_employment_type, load_career_scope, classify_career_family


def age_days(job: Job) -> float | None:
    if not job.published_at:
        return None
    dt = job.published_at
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).total_seconds() / 86400


def hard_filter(job: Job, cfg: dict) -> tuple[bool, str]:
    title = normalize_text(job.title)
    prefs = cfg.get("preferences", {})
    for bad in prefs.get("excluded_title_keywords", []) or []:
        if normalize_text(bad) in title:
            return False, f"excluded title keyword: {bad}"
    required = prefs.get("required_title_keywords", []) or []
    if required and not any(normalize_text(x) in title for x in required):
        return False, "missing required title keyword"
    max_age = cfg.get("search", {}).get("max_age_days", 7)
    a = age_days(job)
    manual_cfg = cfg.get("sources", {}).get("manual_links", {}) or {}
    bypass_manual_age = bool(manual_cfg.get("bypass_age_filter", True))
    if a is not None and a > max_age:
        # A URL supplied explicitly by the user is an intentional review request,
        # not an automatically discovered candidate. If it is still live, evaluate it
        # even when older than the automated-search freshness window.
        if not (job.source == "manual" and bypass_manual_age):
            return False, f"older than {max_age} days"

    typ = detect_employment_type(job)
    allowed = set(prefs.get("allowed_employment_types", []) or [])
    if allowed and typ not in allowed:
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
    text = normalize_text(f"{job.title} {job.description}")
    title = normalize_text(job.title)
    preferred = cfg.get("preferences", {}).get("preferred_keywords", []) or []
    terms = []
    seen = set()
    for t in _profile_terms(profile) + preferred:
        n = normalize_text(str(t))
        if n and n not in seen and len(n) >= 2:
            seen.add(n)
            terms.append(n)

    hits = [t for t in terms if t in text]
    title_hits = [t for t in terms if t in title]

    # Broad capability scoring: eight meaningful evidence hits are already strong;
    # we do not divide by the entire (large) skill inventory.
    score = 15
    score += min(42, len(hits) * 6)
    score += min(12, len(title_hits) * 4)

    scope_path = cfg.get("search", {}).get("career_scope_file", "input/career_scope.yaml")
    scope = load_career_scope(scope_path)
    _, _, tier, family_signal = classify_career_family(job, scope)
    if family_signal > 0:
        tier_bonus = {"core": 20, "adjacent": 15, "stretch": 10}.get(tier, 12)
        score += min(tier_bonus, 5 + family_signal * 2)

    # Generic engineering/R&D titles deserve a chance even when wording differs
    # from the source CV. AI/Codex performs the deeper evidence check afterward.
    generic = [
        "engineer", "ingenieur", "entwicklungsingenieur", "berechnungsingenieur",
        "simulationsingenieur", "konstruktionsingenieur", "research engineer", "r&d engineer",
    ]
    if any(x in title for x in generic):
        score += 6

    return int(max(0, min(100, score)))
