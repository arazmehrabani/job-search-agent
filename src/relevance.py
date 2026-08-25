from __future__ import annotations
from dataclasses import dataclass
from .models import Job
from .utils import normalize_text


# These are intentionally domain-specific. Generic words such as "engineer",
# "development", "project", "automation" and "technical" never make a job relevant
# by themselves.
STRONG_TITLE_PHRASES = (
    "mechanical engineer", "mechanical design engineer", "mechanical development engineer", "production test engineer",
    "maschinenbauingenieur", "entwicklungsingenieur maschinenbau", "konstruktionsingenieur",
    "konstrukteur maschinenbau", "berechnungsingenieur", "cae engineer", "fea engineer",
    "fem engineer", "structural analysis engineer", "structural dynamics engineer",
    "simulation engineer", "simulationsingenieur", "wind energy engineer", "wind turbine engineer",
    "loads engineer", "load simulation", "aeroelastic", "manufacturing engineer",
    "production engineer", "mechanical test engineer", "test engineer mechanical",
    "validation engineer", "verification engineer", "versuchsingenieur", "validierungsingenieur",
    "prüfingenieur", "vibration engineer", "nvh engineer", "mechanical integrity engineer",
    "reliability engineer", "mechatronics engineer", "robotics cae engineer", "robotics engineer",
    "control systems engineer", "controls engineer", "regelungstechnik", "fertigungsingenieur",
    "produktionsingenieur", "product development engineer mechanical", "development engineer test systems",
    "windparkplanung", "wind farm engineer", "wind site assessment", "wind resource engineer",
)

TITLE_BRIDGES = (
    "mechanical", "maschinenbau", "machinery", "machine design", "konstruktion", "cae", "fea", "fem",
    "ansys", "abaqus", "structural", "struktur", "simulation", "simulations", "wind", "windenergie",
    "turbine", "aeroelastic", "openfast", "loads", "lasten", "vibration", "schwing", "nvh",
    "dynamics", "dynamik", "manufacturing", "production engineering", "fertigung", "mechatron",
    "robot", "control", "regelung", "test systems", "validation", "verification", "integrity",
    "reliability", "rotating equipment", "cad", "solidworks", "catia", "siemens nx", "prototype",
    "prototyp", "wind farm", "windpark", "renewable energy", "erneuerbare energien", "plm", "engineering data",
    "regler", "regelung", "ppc", "bess", "battery storage", "batteriespeicher",
)

SOFTWARE_EXCEPTION_BRIDGES = (
    "mechanical", "maschinenbau", "cae", "fea", "fem", "ansys", "structural", "simulation", "simulations",
    "wind turbine", "windenergieanlage", "aeroelastic", "openfast", "vibration", "nvh", "control", "regelung",
    "mechatron", "robot", "test system", "validation", "plm", "cad", "regler", "ppc", "bess",
)

BODY_DOMAIN_PHRASES = (
    "mechanical engineering", "maschinenbau", "mechanical design", "machine design", "machinery", "konstruktion",
    "ansys", "abaqus", "finite element", "fea", "fem", "structural analysis", "structural dynamics",
    "stress analysis", "modal analysis", "harmonic response", "vibration", "resonance", "nvh",
    "solidworks", "catia", "siemens nx", "manufacturing drawings", "fabrication drawings", "bill of materials",
    "design for manufacturing", "manufacturing engineering", "production engineering", "industrialization",
    "wind turbine", "wind energy", "windenergie", "openfast", "aeroelastic", "wind farm", "windpro", "qgis",
    "design load case", "iec 61400", "structural loads", "load simulation", "mechatronics", "motion control",
    "matlab simulink", "control systems", "robotics", "test rig", "validation", "verification", "prototype",
    "mechanical integrity", "rotating equipment", "condition monitoring", "schwingungsanalyse",
    "engineering data analytics", "engineering data", "plm", "product lifecycle management",
)

# Obvious wrong-domain titles. A strong mechanical/wind/simulation/control bridge in
# the same title prevents automatic rejection (e.g. "Control Software Engineer – Wind Turbines").
NEGATIVE_TITLE_GROUPS = {
    "PURE_SOFTWARE_BACKEND": (
        "backend engineer", "backend developer", "backend software", "frontend engineer", "frontend developer",
        "full stack engineer", "full-stack engineer", "fullstack engineer", "devops engineer", "cloud engineer",
        "cloud data engineer", "platform engineer", "data platform engineer", "software engineer", "software developer",
        "web developer", "webdesigner", "wordpress", "site reliability engineer", "rendering programmer",
        "machine learning engineer", "ml engineer", "data engineer", "data scientist", "ai engineer", "sap hcm engineer",
    ),
    "BUSINESS_SALES_MARKETING": (
        "account executive", "sales manager", "sales development", "pre-sales", "presales", "customer success",
        "marketing", "business development", "commercial manager", "founders associate", "client success",
        "partner sales", "revenue", "gtm ", "go-to-market", "customer support engineer",
        "tender manager", "bid manager", "proposal manager",
    ),
    "FINANCE_HR_ADMIN": (
        "finance", "accounting", "payroll", "human resources", " hr ", "recruit", "talent acquisition",
        "people operations", "office management", "compliance officer", "risk management specialist",
    ),
    "DESIGN_MEDIA_NONENGINEERING": (
        "graphic design", "ux/ui", "ux designer", "ui designer", "creative director", "social media", "content creation",
        "branding", "communication and engagement",
    ),
    "SOFTWARE_PRODUCT_DESIGN": (
        "frontend technologies", "software product design", "digital product design", "web product design",
        "website product design", "sitebuilder", "marketplace technologies",
    ),
}

# Some generic engineering titles are worth reading, but they do not earn relevance by
# title alone. Their descriptions must contain a real domain signal.
GENERIC_ENGINEERING_TITLES = (
    "systems engineer", "system engineer", "systemingenieur", "automation engineer", "project engineer",
    "projektingenieur", "research engineer", "r&d engineer", "development engineer", "entwicklungsingenieur",
    "quality engineer", "process engineer", "application engineer", "technical consultant", "product engineer",
    "energy engineer", "ingenieur", "engineer",
)

LOW_VALUE_SKILL_TERMS = {
    "python", "matlab", "excel", "power bi", "development", "design", "automation", "project engineer",
    "technical documentation", "data processing", "visualization", "requirements definition", "concept development",
    "component selection", "ms project", "engineering", "engineer", "systems", "project", "research",
}


@dataclass(frozen=True)
class RelevanceAssessment:
    keep: bool
    reason: str
    title_strength: str
    title_anchor_hits: tuple[str, ...] = ()
    title_bridge_hits: tuple[str, ...] = ()
    body_domain_hits: tuple[str, ...] = ()
    negative_group: str = ""

    @property
    def rank(self) -> int:
        if not self.keep:
            return 0
        base = {"strong": 100, "bridge": 82, "body": 64, "generic": 48}.get(self.title_strength, 40)
        return min(140, base + min(20, len(self.title_anchor_hits) * 4 + len(self.title_bridge_hits) * 2 + len(self.body_domain_hits)))


def _contains(text: str, phrase: str) -> bool:
    t = f" {normalize_text(text)} "
    p = normalize_text(phrase)
    return bool(p and f" {p} " in t)


def _hits(text: str, phrases) -> tuple[str, ...]:
    out = []
    nt = f" {normalize_text(text)} "
    for phrase in phrases:
        p = normalize_text(phrase)
        if p and f" {p} " in nt:
            out.append(phrase)
    return tuple(out)


def title_relevance_gate(job: Job, cfg: dict | None = None) -> RelevanceAssessment:
    """Cheap title-only gate used *before* downloading detail pages.

    It only hard-rejects titles that are obviously in the wrong profession. Ambiguous
    engineering titles survive to description enrichment so we do not lose adjacent roles.
    """
    cfg = cfg or {}
    rcfg = cfg.get("relevance", {}) or {}
    if not bool(rcfg.get("enabled", True)):
        return RelevanceAssessment(True, "relevance gate disabled", "generic")
    if job.source == "manual" and bool(rcfg.get("manual_bypass_title_gate", True)):
        return RelevanceAssessment(True, "manual URL bypasses automatic title rejection", "generic")

    title = job.title or ""
    anchors = _hits(title, STRONG_TITLE_PHRASES)
    bridges = _hits(title, TITLE_BRIDGES)
    if anchors:
        return RelevanceAssessment(True, "strong target title", "strong", anchors, bridges)

    for reason, phrases in NEGATIVE_TITLE_GROUPS.items():
        neg = _hits(title, phrases)
        if not neg:
            continue
        # Pure software is allowed through only when the *title itself* contains a
        # defensible engineering bridge such as simulation/control/CAE/robotics/PLM.
        # Business, finance, HR and media roles are rejected regardless of an industry
        # buzzword such as "renewable energy" in the title.
        if reason == "PURE_SOFTWARE_BACKEND" and _hits(title, SOFTWARE_EXCEPTION_BRIDGES):
            continue
        return RelevanceAssessment(False, reason, "negative", (), (), (), reason)

    if bridges:
        return RelevanceAssessment(True, "relevant engineering bridge in title", "bridge", (), bridges)

    if _hits(title, GENERIC_ENGINEERING_TITLES):
        return RelevanceAssessment(True, "generic engineering title; inspect description", "generic")

    # Non-engineering titles are not automatically rejected here unless they hit a known
    # negative group. The post-enrichment gate gets one chance to find a real domain bridge.
    return RelevanceAssessment(True, "title inconclusive; inspect description", "generic")


def assess_relevance(job: Job, cfg: dict | None = None) -> RelevanceAssessment:
    """Post-enrichment relevance gate using title plus vacancy description."""
    first = title_relevance_gate(job, cfg)
    if not first.keep:
        return first

    title = job.title or ""
    desc = job.description or ""
    anchors = first.title_anchor_hits or _hits(title, STRONG_TITLE_PHRASES)
    bridges = first.title_bridge_hits or _hits(title, TITLE_BRIDGES)
    body = _hits(desc, BODY_DOMAIN_PHRASES)

    if anchors:
        return RelevanceAssessment(True, "strong target title", "strong", anchors, bridges, body)
    if bridges:
        return RelevanceAssessment(True, "relevant engineering bridge in title", "bridge", anchors, bridges, body)
    if body:
        return RelevanceAssessment(True, "relevant engineering domain found in description", "body", anchors, bridges, body)

    rcfg = (cfg or {}).get("relevance", {}) or {}
    if job.source == "manual" and bool(rcfg.get("manual_bypass_domain_gate", True)):
        return RelevanceAssessment(True, "manual URL kept for explicit user review", "generic")

    return RelevanceAssessment(False, "NO_RELEVANT_ENGINEERING_DOMAIN_SIGNAL", "generic")


def specific_profile_hits(job: Job, profile_terms: list[str]) -> tuple[str, ...]:
    """Return evidence terms that are informative enough to affect the PRE score."""
    text = f" {normalize_text((job.title or '') + ' ' + (job.description or ''))} "
    out = []
    seen = set()
    for raw in profile_terms:
        n = normalize_text(str(raw))
        if not n or n in seen or n in LOW_VALUE_SKILL_TERMS or len(n) < 3:
            continue
        seen.add(n)
        if f" {n} " in text:
            out.append(n)
    return tuple(out)
