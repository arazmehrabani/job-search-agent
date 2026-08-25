
from __future__ import annotations
import re, requests
from bs4 import BeautifulSoup
from .models import Job
from .utils import strip_html

EXPIRED_MARKERS = [
    "job is no longer available",
    "position is no longer available",
    "this job has expired",
    "job posting has expired",
    "position has been filled",
    "stelle ist nicht mehr verfügbar",
    "stellenanzeige ist abgelaufen",
    "stelle wurde besetzt",
    "no longer accepting applications",
]
APPLY_WORDS = ("apply", "apply now", "bewerben", "jetzt bewerben", "application")

def check_and_enrich(job: Job, timeout: int=20) -> tuple[str, Job]:
    if not job.url:
        return "unknown", job
    try:
        r=requests.get(job.url, timeout=timeout, allow_redirects=True, headers={
            "User-Agent":"Mozilla/5.0 JobSearchAgent/1.0 (personal-use)"
        })
    except Exception:
        return "unknown", job
    if r.status_code in (404,410):
        return "expired", job
    if r.status_code in (401,403,429):
        return "unknown", job
    if r.status_code >= 500:
        return "unknown", job
    text=r.text or ""
    plain=strip_html(text).lower()
    if any(m in plain for m in EXPIRED_MARKERS):
        return "expired", job

    soup=BeautifulSoup(text,"html.parser")
    if not job.title:
        title = ""
        og=soup.find("meta", attrs={"property":"og:title"})
        if og and og.get("content"): title=og["content"]
        if not title and soup.title: title=soup.title.get_text(" ", strip=True)
        job.title=(title or "Job").strip()[:180]
    if not job.description or len(job.description)<80:
        # Use main/article/body text; trim to protect API costs.
        container=soup.find("main") or soup.find("article") or soup.body
        if container:
            job.description=strip_html(str(container))[:16000]
    if not job.company:
        ogsite=soup.find("meta", attrs={"property":"og:site_name"})
        if ogsite and ogsite.get("content"):
            job.company=ogsite["content"][:120]
    if not job.apply_url:
        for a in soup.find_all("a", href=True):
            label=a.get_text(" ",strip=True).lower()
            if any(w in label for w in APPLY_WORDS):
                job.apply_url=requests.compat.urljoin(r.url,a["href"])
                break
    job.url=r.url
    return "active", job
