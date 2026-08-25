from __future__ import annotations
import json
import re
from pathlib import Path
from collections.abc import Mapping
from typing import Any, Iterable, TypeAlias
from .models import Job

_TOKEN = re.compile(r"[a-zA-ZÀ-ÿ0-9+#.-]{3,}")
_STOP = {
    "and","the","with","for","from","that","this","using","into","through",
    "und","der","die","das","mit","für","von","eine","einer","einem","sowie",
    "engineer","engineering","ingenieur","job","role","position","experience",
}


RegistryInput: TypeAlias = str | Path | Mapping[str, Any] | None


def _registry_path(value: RegistryInput) -> str:
    """Accept either the config dict or a direct registry path."""
    if isinstance(value, dict):
        return str(value.get("evidence", {}).get("registry", "input/evidence/evidence.json"))
    if value is None:
        return "input/evidence/evidence.json"
    return str(value)


def load_evidence_registry(
    value: RegistryInput = "input/evidence/evidence.json",
) -> list[dict[str, Any]]:
    p = Path(_registry_path(value))
    if not p.exists():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    items = data.get("evidence", data if isinstance(data, list) else [])
    return [
        x for x in items
        if isinstance(x, dict) and x.get("id") and x.get("claim") and x.get("verified", True)
    ]


def _tokens(text: str) -> set[str]:
    return {
        t.lower().strip(".-") for t in _TOKEN.findall(text or "")
        if t.lower().strip(".-") not in _STOP
    }


def retrieve_evidence(
    job: Job,
    registry_or_cfg,
    career_family: str = "",
    limit: int | None = None,
) -> list[dict]:
    """Rank verified evidence for a vacancy.

    `registry_or_cfg` can be the already loaded registry (preferred for pipelines) or
    the full config dict (kept for compatibility with V1.4.x helpers/tests).
    """
    if isinstance(registry_or_cfg, list):
        items = registry_or_cfg
        default_limit = 16
    else:
        cfg = registry_or_cfg if isinstance(registry_or_cfg, dict) else {}
        items = load_evidence_registry(cfg)
        default_limit = int(cfg.get("evidence", {}).get("max_items_per_job", 16) or 16)
    if not items:
        return []
    limit = max(1, int(limit or default_limit))
    job_text = " ".join([job.title or "", job.description or "", career_family or ""]).lower()
    jt = _tokens(job_text)
    scored: list[tuple[float, dict]] = []
    for item in items:
        claim = str(item.get("claim", ""))
        keywords = [str(x).lower() for x in item.get("keywords", [])]
        tags = [str(x).lower() for x in item.get("tags", [])]
        families = [str(x) for x in (item.get("career_families", []) or item.get("tags", []))]
        it = _tokens(claim + " " + " ".join(keywords) + " " + " ".join(tags))
        overlap = len(jt & it)
        keyword_hits = sum(1 for kw in keywords if kw and kw in job_text)
        score = overlap + keyword_hits * 3.0
        if career_family and career_family in families:
            score += 5.0
        if item.get("category") in {"education", "language"}:
            score += 1.5
        if item.get("category") == "professional_experience":
            score += 0.75
        scored.append((score, item))
    scored.sort(key=lambda x: (x[0], str(x[1].get("id"))), reverse=True)
    selected = [item for score, item in scored if score > 0][:limit]

    # Always keep basic education/language truth available to the evaluator when room exists.
    have = {x.get("id") for x in selected}
    for item in items:
        if len(selected) >= limit:
            break
        if item.get("category") in {"education", "language"} and item.get("id") not in have:
            selected.append(item)
            have.add(item.get("id"))
    return selected


def evidence_by_ids(ids: Iterable[str], registry_or_cfg) -> list[dict]:
    wanted = {str(x) for x in ids if x}
    items = registry_or_cfg if isinstance(registry_or_cfg, list) else load_evidence_registry(registry_or_cfg)
    return [x for x in items if x.get("id") in wanted]


def evidence_payload(items: list[dict]) -> list[dict]:
    allowed = (
        "id", "claim", "category", "source", "source_cv", "period",
        "keywords", "tags", "career_families",
    )
    return [{k: item.get(k) for k in allowed if k in item} for item in items]
