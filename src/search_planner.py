from __future__ import annotations
import hashlib
import json
from pathlib import Path

from .ai import AIEngine
from .career import load_career_scope
from .evidence import load_evidence_registry, evidence_payload


def _dedupe(items):
    out = []
    seen = set()
    for item in items:
        q = str(item or "").strip()
        k = q.lower()
        if q and k not in seen:
            seen.add(k)
            out.append(q)
    return out


def _load_ai_queries(cfg: dict, profile: dict, ai: AIEngine) -> list[str]:
    scfg = cfg.get("search", {})
    if not scfg.get("auto_from_cv", False) or not ai.enabled:
        return []
    registry = load_evidence_registry(cfg.get("evidence", {}).get("registry", "input/evidence/evidence.json"))
    if not registry:
        return []
    evidence_items = evidence_payload(registry)
    max_auto = int(scfg.get("max_auto_queries", 14))
    broad = bool(scfg.get("broad_search", True))
    sig_src = json.dumps(profile, sort_keys=True, ensure_ascii=False) + json.dumps(evidence_items, sort_keys=True, ensure_ascii=False) + str(broad) + str(max_auto)
    sig = hashlib.sha256(sig_src.encode("utf-8")).hexdigest()
    cache = Path("output/auto_cv_queries.json")
    try:
        obj = json.loads(cache.read_text(encoding="utf-8"))
        if obj.get("signature") == sig:
            return list(obj.get("queries", []) or [])
    except Exception:
        pass
    queries = ai.suggest_search_queries(evidence_items, profile, broad=broad, limit=max_auto)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(
        json.dumps({"signature": sig, "queries": queries}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return queries


def _career_queries(cfg: dict) -> tuple[list[str], list[str], dict]:
    scfg = cfg.get("search", {})
    scope = load_career_scope(scfg.get("career_scope_file", "input/career_scope.yaml"))
    if not scfg.get("use_career_scope", True):
        return [], [], scope
    included = set(scfg.get("include_tiers", ["core", "adjacent", "stretch"]) or [])
    core = []
    rotating = []
    languages = set(scfg.get("job_languages", ["en", "de"]) or ["en", "de"])
    for _, data in (scope.get("families", {}) or {}).items():
        tier = str(data.get("tier", "adjacent"))
        if tier not in included:
            continue
        qs = []
        if "en" in languages:
            qs.extend(data.get("queries_en", []) or [])
        if "de" in languages:
            qs.extend(data.get("queries_de", []) or [])
        if tier == "core":
            core.extend(qs)
        else:
            rotating.extend(qs)
    return _dedupe(core), _dedupe(rotating), scope


def _rotating_slice(items: list[str], slots: int, state_path: Path) -> list[str]:
    if slots <= 0 or not items:
        return []
    if slots >= len(items):
        return items[:]
    start = 0
    try:
        obj = json.loads(state_path.read_text(encoding="utf-8"))
        start = int(obj.get("next_index", 0)) % len(items)
    except Exception:
        start = 0
    selected = [items[(start + i) % len(items)] for i in range(slots)]
    next_index = (start + slots) % len(items)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"next_index": next_index}, indent=2), encoding="utf-8")
    return selected


def build_search_queries(cfg: dict, profile: dict, ai: AIEngine) -> list[str]:
    scfg = cfg.get("search", {})
    anchors = list(scfg.get("always_queries", []) or scfg.get("queries", []) or [])

    if scfg.get("auto_from_profile", True):
        anchors.extend(((profile.get("job_preferences") or {}).get("roles") or []))
    anchors.extend(scfg.get("broader_queries", []) or [])
    anchors = _dedupe(anchors)

    core, adjacent_stretch, scope = _career_queries(cfg)
    ai_queries = _load_ai_queries(cfg, profile, ai)

    # Keep deliberate anchors first. Core-family queries are next. Adjacent/stretch
    # and AI-generated queries rotate to broaden coverage without excessive API calls.
    fixed = _dedupe(anchors)
    fixed_keys = {q.lower() for q in fixed}
    rotating_pool = [q for q in _dedupe(core + adjacent_stretch + ai_queries) if q.lower() not in fixed_keys]
    max_cycle = max(1, int(scfg.get("max_queries_per_cycle", 28)))

    if len(fixed) >= max_cycle:
        selected = fixed[:max_cycle]
    else:
        slots = max_cycle - len(fixed)
        state_path = Path(scfg.get("query_rotation_state", "output/query_rotation.json"))
        selected = _dedupe(fixed + _rotating_slice(rotating_pool, slots, state_path))

    plan = {
        "selected_queries": selected,
        "always_queries": anchors,
        "core_career_queries": core,
        "rotating_pool": rotating_pool,
        "ai_generated_queries": ai_queries,
        "career_families": {
            k: {"label": v.get("label"), "tier": v.get("tier")}
            for k, v in (scope.get("families", {}) or {}).items()
        },
    }
    out = Path(scfg.get("search_plan_output", "output/search_plan.json"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return selected or [""]
