from __future__ import annotations

import json
import re
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup

from .models import Job
from .utils import canonical_url, parse_datetime, strip_html

EXPIRED_MARKERS = [
    "job is no longer available", "position is no longer available", "this job has expired",
    "job posting has expired", "position has been filled", "stelle ist nicht mehr verfügbar",
    "stellenanzeige ist abgelaufen", "stelle wurde besetzt", "no longer accepting applications",
    "job has been removed", "vacancy has been closed",
]
APPLY_WORDS = ("apply", "apply now", "bewerben", "jetzt bewerben", "application")


def _first(*values):
    for value in values:
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _jobpostings(obj):
    if isinstance(obj, dict):
        typ = obj.get("@type")
        types = typ if isinstance(typ, list) else [typ]
        if any(str(t).lower() == "jobposting" for t in types if t):
            yield obj
        for v in obj.values():
            yield from _jobpostings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _jobpostings(v)


def _extract_jsonld(soup: BeautifulSoup) -> dict:
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text("", strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        for item in _jobpostings(data):
            return item
    return {}


def _jsonld_location(jp: dict) -> str:
    loc = jp.get("jobLocation") or jp.get("jobLocationType") or ""
    if isinstance(loc, list):
        loc = loc[0] if loc else ""
    if isinstance(loc, dict):
        addr = loc.get("address") or {}
        if isinstance(addr, dict):
            vals = [addr.get("addressLocality"), addr.get("addressRegion"), addr.get("addressCountry")]
            country = vals[-1]
            if isinstance(country, dict):
                vals[-1] = country.get("name") or country.get("@id")
            return ", ".join(str(x) for x in vals if x)
        return _first(loc.get("name"))
    return str(loc or "").strip()


def _field_from_plain(plain: str, label: str, next_labels: list[str]) -> str:
    stops = "|".join(re.escape(x) for x in next_labels)
    pattern = rf"{re.escape(label)}\s*:?\s*(.+?)(?=\s+(?:{stops})\s*:?\s*|$)"
    m = re.search(pattern, plain, flags=re.I | re.S)
    return re.sub(r"\s+", " ", m.group(1)).strip(" :-") if m else ""


def _source_id_from_url(url: str) -> str:
    path = urlsplit(url).path
    # Ashby UUID
    m = re.search(r"/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?:/|$)", path, re.I)
    if m:
        return m.group(1).lower()
    # SuccessFactors/TÜV SÜD uses /6328-en_US or /6760-en_US.
    m = re.search(r"/(\d+)-(?:[a-z]{2}_[A-Z]{2})(?:/)?$", path)
    if m:
        return m.group(1)
    return ""


def _ashby_company_from_url(url: str) -> str:
    parts = [p for p in urlsplit(url).path.split("/") if p]
    if not parts:
        return ""
    slug = parts[0]
    words = slug.replace("-", " ").split()
    rendered = " ".join(w.upper() if w.lower() in {"gmbh", "ag", "se", "kg"} else w.capitalize() for w in words)
    # Preserve common robotics brand styling where possible without inventing a legal name.
    if rendered.lower().startswith("neura robotics"):
        return "NEURA Robotics GmbH" if "gmbh" in slug.lower() else "NEURA Robotics"
    return rendered


def _apply_jsonld(job: Job, jp: dict):
    if not jp:
        return
    org = jp.get("hiringOrganization") or {}
    if isinstance(org, dict):
        company = org.get("name") or ""
    else:
        company = str(org or "")
    job.title = _first(job.title, jp.get("title"))
    job.company = _first(job.company, company)
    job.location = _first(job.location, _jsonld_location(jp))
    desc = strip_html(str(jp.get("description") or ""))
    if len(desc) > len(job.description or ""):
        job.description = desc[:20000]
    job.published_at = job.published_at or parse_datetime(jp.get("datePosted"))
    if jp.get("employmentType"):
        typ = jp.get("employmentType")
        if isinstance(typ, list):
            typ = ", ".join(map(str, typ))
        job.metadata["employment_type_raw"] = str(typ)
    if jp.get("validThrough"):
        job.metadata["valid_through"] = str(jp.get("validThrough"))


def _apply_successfactors(job: Job, plain: str):
    labels = ["Work Area", "Country/Region", "Job Location", "Working Model", "Employment Type", "Company", "Org Unit Code", "Requisition ID"]
    company = _field_from_plain(plain, "Company", ["Org Unit Code", "Requisition ID"])
    location = _field_from_plain(plain, "Job Location", ["Working Model", "Employment Type", "Company", "Org Unit Code", "Requisition ID"])
    employment = _field_from_plain(plain, "Employment Type", ["Company", "Org Unit Code", "Requisition ID"])
    working_model = _field_from_plain(plain, "Working Model", ["Employment Type", "Company", "Org Unit Code", "Requisition ID"])
    req = _field_from_plain(plain, "Requisition ID", [])
    job.company = _first(job.company, company)
    job.location = _first(job.location, location)
    if employment:
        job.metadata["employment_type_raw"] = employment
    if working_model:
        job.metadata["working_model"] = working_model
    if req:
        m = re.search(r"\d+", req)
        if m:
            job.source_id = m.group(0)


def _apply_ashby(job: Job, plain: str, url: str):
    # Ashby's public job pages render standardized labels when server-side content is available.
    location = _field_from_plain(plain, "Location", ["Employment Type", "Location Type", "Department", "Overview", "Application"])
    employment = _field_from_plain(plain, "Employment Type", ["Location Type", "Department", "Overview", "Application"])
    location_type = _field_from_plain(plain, "Location Type", ["Department", "Overview", "Application"])
    job.company = _first(job.company, _ashby_company_from_url(url))
    job.location = _first(job.location, location)
    if employment:
        job.metadata["employment_type_raw"] = employment
    if location_type:
        job.metadata["working_model"] = location_type


def check_and_enrich(job: Job, timeout: int = 20) -> tuple[str, Job]:
    if not job.url:
        return "unknown", job
    try:
        r = requests.get(job.url, timeout=timeout, allow_redirects=True, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"
        })
    except Exception:
        return "unknown", job
    if r.status_code in (404, 410):
        return "expired", job
    if r.status_code in (401, 403, 429) or r.status_code >= 500:
        return "unknown", job

    text = r.text or ""
    plain_full = strip_html(text)
    plain_low = plain_full.lower()
    if any(m in plain_low for m in EXPIRED_MARKERS):
        return "expired", job

    soup = BeautifulSoup(text, "html.parser")
    jp = _extract_jsonld(soup)
    _apply_jsonld(job, jp)

    final_url = canonical_url(r.url)
    host = urlsplit(final_url).netloc.lower()
    extracted_id = _source_id_from_url(final_url)
    if extracted_id:
        job.source_id = extracted_id

    # Prefer H1/OG title over browser-title boilerplate.
    if not job.title:
        h1 = soup.find("h1")
        og = soup.find("meta", attrs={"property": "og:title"})
        title = _first(
            h1.get_text(" ", strip=True) if h1 else "",
            og.get("content") if og else "",
            soup.title.get_text(" ", strip=True) if soup.title else "",
        )
        title = re.sub(r"\s+(?:Job Details|Job Description)\s*\|.*$", "", title, flags=re.I)
        job.title = title[:220].strip()

    if "jobs.tuvsud.com" in host:
        _apply_successfactors(job, plain_full)
        job.metadata["platform"] = "successfactors"
    elif host.endswith("ashbyhq.com"):
        _apply_ashby(job, plain_full, final_url)
        job.metadata["platform"] = "ashby"

    if not job.description or len(job.description) < 120:
        container = soup.find("main") or soup.find("article") or soup.body
        if container:
            job.description = strip_html(str(container))[:20000]

    if not job.company:
        ogsite = soup.find("meta", attrs={"property": "og:site_name"})
        if ogsite and ogsite.get("content"):
            site = str(ogsite["content"]).strip()
            if site.lower() not in {"jobs", "careers", "job details", "ashby"}:
                job.company = site[:140]

    if not job.apply_url:
        for a in soup.find_all("a", href=True):
            label = a.get_text(" ", strip=True).lower()
            if any(w == label or w in label for w in APPLY_WORDS):
                job.apply_url = requests.compat.urljoin(r.url, a["href"])
                break

    job.url = final_url
    if not job.apply_url:
        job.apply_url = final_url
    return "active", job
