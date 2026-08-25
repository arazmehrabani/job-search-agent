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
    title_raw = (job.title or "").lower()
    body_raw = (job.description or "")[:12000].lower()
    title = " " + normalize_text(title_raw) + " "
    body = " " + normalize_text(body_raw) + " "

    de = sum(body.count(m) for m in GERMAN_MARKERS)
    en = sum(body.count(m) for m in ENGLISH_MARKERS)
    # The vacancy title is highly informative and should beat English ATS boilerplate.
    de_title_terms = ["werkstudent", "ingenieur", "windenergie", "bereich", "türme", "fundamente", "maschinenbau", "entwicklung", "berechnung", "praktikum", "masterarbeit"]
    en_title_terms = ["engineer", "engineering", "working student", "intern", "internship", "specialist", "manager", "developer"]
    de += 4 * sum(1 for x in de_title_terms if x in title_raw)
    en += 3 * sum(1 for x in en_title_terms if x in title_raw)
    de += 2 * sum((title_raw + body_raw).count(ch) for ch in ("ä", "ö", "ü", "ß"))
    if de >= max(4, int(en * 1.05)):
        return "de"
    if en >= 2:
        return "en"
    return "de" if de > en else "en"


def detect_german_requirement(job: Job) -> str:
    """Conservative language requirement: high/medium/basic/preferred/none."""
    raw = f"{job.title} {job.description[:16000]}".lower()
    text = " " + normalize_text(raw) + " "

    preferred = [
        "german is advantageous", "german advantageous", "german is a plus", "german would be a plus",
        "deutsch von vorteil", "deutschkenntnisse von vorteil", "deutsch wünschenswert", "deutschkenntnisse wünschenswert",
        "ideally german", "idealerweise deutsch",
    ]
    # Preferred wording must be checked before generic words like Deutschkenntnisse.
    if any(x in raw or x in text for x in preferred):
        return "preferred"

    high = [
        " c1 ", " c2 ", "muttersprach", "verhandlungssicher", "fließend", "fliessend",
        "fluent german", "fluent in german", "german fluency", "native german", "excellent german",
        "sehr gute deutschkenntnisse", "sehr gutes deutsch", "verhandlungssichere deutschkenntnisse",
    ]
    medium = [" b2 ", "gute deutschkenntnisse", "good german", "german b2", "good command of german"]
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


def detect_employment_profile(job: Job) -> dict:
    """Return orthogonal employment dimensions instead of forcing one label."""
    raw = f"{job.title} {job.description[:10000]} {(job.metadata or {}).get('employment_type_raw','')}".lower()
    text = " " + normalize_text(raw) + " "
    title = " " + normalize_text(job.title or "") + " "

    def has_phrase(phrase: str, hay: str = text) -> bool:
        n = normalize_text(phrase)
        # Word-boundary aware so 'intern' no longer matches 'international'.
        return bool(re.search(r"(?<![a-z0-9äöüß])" + re.escape(n) + r"(?![a-z0-9äöüß])", hay))

    career_stage = "professional"
    if any(has_phrase(x, title) or has_phrase(x) for x in ["working student", "werkstudent", "werkstudentin", "studentische aushilfe"]):
        career_stage = "working_student"
    elif any(has_phrase(x, title) or has_phrase(x) for x in ["master thesis", "masterarbeit", "abschlussarbeit", "thesis student"]):
        career_stage = "master_thesis"
    elif any(has_phrase(x, title) or has_phrase(x) for x in ["internship", "intern", "praktikum", "praktikant", "praktikantin"]):
        career_stage = "internship"

    schedule = "unknown"
    if any(has_phrase(x) for x in ["full time", "full-time"]) or "vollzeit" in raw:
        schedule = "full_time"
    elif any(has_phrase(x) for x in ["part time", "part-time"]) or "teilzeit" in raw:
        schedule = "part_time"

    contract = "unknown"
    if any(has_phrase(x) for x in ["fixed term", "fixed-term"]) or "befristet" in raw and "unbefristet" not in raw:
        contract = "fixed_term"
    elif any(has_phrase(x) for x in ["regular", "permanent"]) or "unbefristet" in raw:
        contract = "regular"

    # The legacy primary type remains useful for CV selection and old configs.
    if career_stage != "professional":
        primary = career_stage
    elif schedule != "unknown":
        primary = schedule
    elif contract == "fixed_term":
        primary = "fixed_term"
    else:
        primary = "professional"
    return {"primary": primary, "career_stage": career_stage, "schedule": schedule, "contract": contract}


def detect_employment_type(job: Job) -> str:
    return detect_employment_profile(job)["primary"]


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
