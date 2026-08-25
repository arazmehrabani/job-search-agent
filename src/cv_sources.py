from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from .models import Job
from .utils import normalize_text


@dataclass
class CVSource:
    key: str
    path: Path
    source_language: str = "en"
    focus_keywords: list[str] | None = None
    priority: int = 0
    career_families: list[str] | None = None
    employment_types: list[str] | None = None
    role: str = "base"  # base | specialist | evidence

    @property
    def exists(self) -> bool:
        return self.path.exists()

    def read(self) -> str:
        return self.path.read_text(encoding="utf-8")


def configured_cv_sources(cfg: dict) -> list[CVSource]:
    dcfg = cfg.get("documents", {}) or {}
    out: list[CVSource] = []
    for key, data in (dcfg.get("cv_sources", {}) or {}).items():
        raw_path = str(data.get("path", "")).strip()
        if not raw_path:
            continue
        src = CVSource(
            key=str(key),
            path=Path(raw_path),
            source_language=str(data.get("source_language", "en")).lower(),
            focus_keywords=[str(x) for x in (data.get("focus_keywords", []) or [])],
            priority=int(data.get("priority", 0) or 0),
            career_families=[str(x) for x in (data.get("career_families", []) or [])],
            employment_types=[str(x) for x in (data.get("employment_types", []) or [])],
            role=str(data.get("role", "base")),
        )
        if src.exists:
            out.append(src)
    if not out:
        fallback = Path(dcfg.get("master_cv", "input/master_cv.tex"))
        if fallback.exists():
            out.append(CVSource("default", fallback, "en", [], 0))
    return out


def select_cv_source(
    job: Job,
    cfg: dict,
    target_language: str | None = None,
    career_family: str | None = None,
    employment_type: str | None = None,
) -> CVSource | None:
    """Choose the best *layout/base* CV, not the only factual evidence source.

    V1.3 prefers a CV already written in the vacancy language, then the domain/family,
    then keyword relevance. The AI is separately given the entire evidence bundle, so
    facts are not lost just because the selected layout is Mechanical or Wind.
    """
    sources = configured_cv_sources(cfg)
    if not sources:
        return None
    title = normalize_text(job.title)
    text = normalize_text(f"{job.title} {job.description[:12000]}")
    lang = (target_language or "").lower().strip()
    family = str(career_family or "")
    emp = str(employment_type or "")
    scored: list[tuple[int, CVSource]] = []
    for src in sources:
        score = src.priority
        if lang:
            score += 35 if src.source_language == lang else -18
        if family and family in (src.career_families or []):
            score += 28
        if src.employment_types:
            score += 35 if emp in src.employment_types else -45
        if src.role == "evidence":
            score -= 80  # factual source only; avoid using it as layout unless no alternative exists.
        elif src.role == "specialist":
            score += 3
        for kw in src.focus_keywords or []:
            n = normalize_text(kw)
            if not n:
                continue
            if n in title:
                score += 8
            elif n in text:
                score += 2
        scored.append((score, src))
    scored.sort(key=lambda x: (x[0], x[1].key), reverse=True)
    return scored[0][1]


def combined_cv_text(cfg: dict, max_chars_each: int = 30000) -> str:
    """Evidence library from every configured factual CV source."""
    chunks = []
    for src in configured_cv_sources(cfg):
        try:
            text = src.read()[:max_chars_each]
        except Exception:
            continue
        chunks.append(
            f"\n===== SOURCE CV: {src.key} | language={src.source_language} | role={src.role} | path={src.path} =====\n{text}"
        )
    return "\n".join(chunks)
