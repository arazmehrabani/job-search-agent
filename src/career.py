from __future__ import annotations
from pathlib import Path
import re
import yaml

from .models import Job
from .utils import normalize_text

GERMAN_MARKERS = {
    " und ", " der ", " die ", " das ", " wir ", " sie ", " ihr ", " ihre ",
    "aufgaben", "anforderungen", "kenntnisse", "erfahrung", "bewerbung", "vollzeit",
    "teilzeit", "werkstudent", "praktikum", "masterarbeit", "abschlussarbeit",
    "ingenieur", "ingenieurin", "maschinenbau", "windenergie", "entwicklung",
    "konstruktion", "berechnung", "standort", "deutschkenntnisse", "m w d",
}
ENGLISH_MARKERS = {
    " and ", " the ", " we ", " you ", " your ", " responsibilities", "requirements",
    "experience", "skills", "application", "full time", "part time", "working student",
    "internship", "master thesis", "engineer", "engineering", "development", "design",
    "location", "english", "german",
}


def load_career_scope(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        return {"families": {}}
    with p.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {"families": {}}


def detect_job_language(job: Job) -> str:
    text = " " + normalize_text(f"{job.title} {job.description[:12000]}") + " "
    de = sum(text.count(m) for m in GERMAN_MARKERS)
    en = sum(text.count(m) for m in ENGLISH_MARKERS)
    # German characters are a useful extra hint without being decisive alone.
    raw = f"{job.title} {job.description[:12000]}".lower()
    de += 2 * sum(raw.count(ch) for ch in ("ä", "ö", "ü", "ß"))
    if de >= max(3, int(en * 1.10)):
        return "de"
    if en >= 2:
        return "en"
    # Many German job titles still use English terminology. Default remains English
    # unless German evidence is stronger.
    return "en"



def detect_german_requirement(job: Job) -> str:
    """Return a conservative explicit German-language requirement category.

    This is a risk signal only. V1.3 deliberately does not hard-filter German jobs
    because the candidate wants to apply while improving from B1.
    """
    raw = f"{job.title} {job.description[:12000]}".lower()
    text = " " + normalize_text(raw) + " "
    high = [
        " c1 ", " c2 ", "muttersprach", "verhandlungssicher", "fließend", "fliessend",
        "fluent german", "native german", "excellent german", "sehr gute deutschkenntnisse",
    ]
    medium = [" b2 ", "gute deutschkenntnisse", "good german", "german b2"]
    basic = [" b1 ", "grundkenntnisse deutsch", "basic german", "german b1"]
    if any(x in raw or x in text for x in high):
        return "c1_plus_or_fluent"
    if any(x in raw or x in text for x in medium):
        return "b2_or_good"
    if any(x in raw or x in text for x in basic):
        return "b1_or_basic"
    if any(x in raw or x in text for x in ["deutschkenntnisse", "german language", "german skills", "kenntnisse der deutschen sprache"]):
        return "required_unspecified"
    return "none"

def detect_employment_type(job: Job) -> str:
    text = " " + normalize_text(f"{job.title} {job.description[:8000]}") + " "
    patterns = [
        ("working_student", ["working student", "werkstudent", "werkstudentin", "studentische aushilfe"]),
        ("master_thesis", ["master thesis", "masterarbeit", "abschlussarbeit", "thesis student"]),
        ("internship", ["internship", "intern ", "praktikum", "praktikant", "praktikantin"]),
        ("part_time", ["part time", "part-time", "teilzeit"]),
        ("full_time", ["full time", "full-time", "vollzeit", "unbefristet"]),
        ("fixed_term", ["fixed term", "fixed-term", "befristet"]),
    ]
    title = normalize_text(job.title)
    # Student/thesis/internship title signals should win over generic full-time words
    # sometimes present in boilerplate.
    for typ, terms in patterns[:3]:
        if any(normalize_text(t) in title for t in terms):
            return typ
    for typ, terms in patterns:
        if any(normalize_text(t) in text for t in terms):
            return typ
    return "unknown"


def classify_career_family(job: Job, scope: dict) -> tuple[str, str, str, int]:
    text = " " + normalize_text(f"{job.title} {job.description[:12000]}") + " "
    families = scope.get("families", {}) or {}
    best_key = "general_engineering"
    best_label = "General / interdisciplinary engineering"
    best_tier = "adjacent"
    best_score = 0
    for key, data in families.items():
        terms = data.get("match_keywords", []) or []
        score = 0
        for term in terms:
            n = normalize_text(str(term))
            if not n:
                continue
            if n in normalize_text(job.title):
                score += 4
            elif n in text:
                score += 1
        if score > best_score:
            best_score = score
            best_key = key
            best_label = str(data.get("label", key))
            best_tier = str(data.get("tier", "adjacent"))
    return best_key, best_label, best_tier, best_score


def family_transferable_terms(scope: dict, family_key: str) -> list[str]:
    data = (scope.get("families", {}) or {}).get(family_key, {}) or {}
    return [str(x) for x in (data.get("match_keywords", []) or [])]
