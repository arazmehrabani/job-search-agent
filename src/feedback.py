from __future__ import annotations
import json
from collections import defaultdict
from pathlib import Path


def family_feedback_adjustments(db, cfg: dict) -> dict[str, float]:
    fcfg = cfg.get("feedback", {}) or {}
    if not fcfg.get("learning_enabled", True):
        return {}
    min_samples = int(fcfg.get("min_samples_for_adjustment", 5))
    max_adj = float(fcfg.get("max_priority_adjustment", 8))
    weights = {
        "APPLY": 1.0,
        "SAVE": 0.45,
        "SKIP": -1.0,
        "APPLIED": 1.1,
        "INTERVIEW": 1.4,
        "OFFER": 1.7,
        "REJECTED": -0.25,
    }
    sums = defaultdict(float)
    counts = defaultdict(int)
    for row in db.rows_with_feedback():
        try:
            match = json.loads(row["match_json"] or "{}")
        except Exception:
            match = {}
        fam = str(match.get("career_family", "") or "")
        decision = str(row["user_decision"] or "").upper()
        if not fam or decision not in weights:
            continue
        sums[fam] += weights[decision]
        counts[fam] += 1
    out = {}
    for fam, n in counts.items():
        if n < min_samples:
            continue
        avg = sums[fam] / n  # roughly -1..1.7
        out[fam] = max(-max_adj, min(max_adj, avg * (max_adj / 1.5)))
    return out


def write_feedback_summary(db, cfg: dict, output: str = "output/feedback_summary.json") -> Path:
    decisions = defaultdict(int)
    families = defaultdict(lambda: defaultdict(int))
    for row in db.rows_with_feedback():
        decision = str(row["user_decision"] or "").upper()
        if not decision:
            continue
        decisions[decision] += 1
        try:
            match = json.loads(row["match_json"] or "{}")
        except Exception:
            match = {}
        fam = str(match.get("career_family_label", match.get("career_family", "Unknown")) or "Unknown")
        families[fam][decision] += 1
    obj = {
        "decisions": dict(sorted(decisions.items())),
        "career_families": {k: dict(v) for k, v in sorted(families.items())},
        "priority_adjustments": family_feedback_adjustments(db, cfg),
    }
    p = Path(output)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    return p
