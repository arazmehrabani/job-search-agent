from __future__ import annotations
from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Optional, Any


@dataclass
class Job:
    source: str
    source_id: str
    title: str
    company: str
    location: str
    url: str
    apply_url: str = ""
    description: str = ""
    published_at: Optional[datetime] = None
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    currency: str = "EUR"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        if self.published_at:
            d["published_at"] = self.published_at.isoformat()
        return d


@dataclass
class MatchResult:
    # Fit answers "how well does the verified evidence satisfy the vacancy?"
    score: int
    recommendation: str
    # Priority answers "how strongly should this candidate actually consider applying?"
    priority_score: int = 0
    priority_label: str = ""
    priority_reasons: list[str] = field(default_factory=list)

    required_match: int = 0
    nice_to_have_match: int = 0
    strong_matches: list[str] = field(default_factory=list)
    partial_matches: list[str] = field(default_factory=list)
    missing_required: list[str] = field(default_factory=list)
    missing_nice_to_have: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    reasoning: str = ""
    source: str = "heuristic"
    screen_score: int = 0
    screen_decision: str = ""

    # Traceability
    evidence_ids: list[str] = field(default_factory=list)
    requirement_evidence: list[dict[str, Any]] = field(default_factory=list)
    decision: str = ""
    decision_reasons: list[str] = field(default_factory=list)

    job_language: str = "en"
    employment_type: str = "unknown"
    career_family: str = "general_engineering"
    career_family_label: str = "General / interdisciplinary engineering"
    career_tier: str = "adjacent"
    transferability: str = ""
    source_cv: str = ""
    german_requirement: str = "none"
    career_stage: str = "professional"
    schedule: str = "unknown"
    contract: str = "unknown"
    technical_fit: int = 0
    experience_fit: int = 0
    language_fit: int = 0
    education_fit: int = 0

    def to_dict(self) -> dict:
        return asdict(self)
