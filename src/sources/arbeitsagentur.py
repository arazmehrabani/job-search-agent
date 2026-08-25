from __future__ import annotations
from datetime import datetime, timedelta, timezone
import random
import re
import time
from typing import Any
from urllib.parse import urlencode, urljoin
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

from .base import JobSource
from ..models import Job
from ..utils import fingerprint


BASE = "https://www.arbeitsagentur.de"
SEARCH_URL = BASE + "/jobsuche/suche"


class ArbeitsagenturSource(JobSource):
    """Broad discovery from the public Bundesagentur für Arbeit Jobsuche pages.

    BA does not publish an official vacancy-search API. This connector therefore
    uses the public search HTML, respects robots.txt (which currently allows `/`),
    keeps a conservative per-run query cap, and lets V1.6/V1.7 page verification
    fetch the selected detail pages politely through the shared HTTP policy.
    """

    name = "arbeitsagentur"
    category = "broad"

    def __init__(self, cfg: dict[str, Any] | None = None):
        self.cfg = cfg or {}
        self.timeout = int(self.cfg.get("timeout_seconds", 25) or 25)
        self.max_queries = max(1, int(self.cfg.get("max_queries_per_run", 12) or 12))
        self.user_agent = str(self.cfg.get("user_agent") or "JobSearchAgent/1.9.0")
        self.min_delay = float(self.cfg.get("min_delay_seconds", 1.5) or 0.0)
        self.jitter = float(self.cfg.get("delay_jitter_seconds", 0.25) or 0.0)
        self.respect_robots = bool(self.cfg.get("respect_robots_txt", True))
        self.robots_fail_open = bool(self.cfg.get("robots_fail_open", True))
        self._last_request = 0.0
        self._robots_allowed_cache = None

    def health(self) -> dict[str, Any]:
        return {"name": self.name, "category": self.category, "automatic": True,
                "configured": True, "operational": True,
                "reason": f"public Jobsuche HTML; max {self.max_queries} queries/run"}

    @staticmethod
    def _angebot_for(query: str) -> int:
        q = (query or "").lower()
        student_terms = ("werkstudent", "working student", "internship", "praktikum", "trainee", "masterarbeit", "master thesis", "thesis")
        return 34 if any(x in q for x in student_terms) else 1

    def _wait(self):
        elapsed = time.monotonic() - self._last_request
        target = self.min_delay + (random.random() * self.jitter if self.jitter > 0 else 0.0)
        if elapsed < target:
            time.sleep(target - elapsed)

    def _robots_allowed(self) -> bool:
        if not self.respect_robots:
            return True
        if self._robots_allowed_cache is not None:
            return bool(self._robots_allowed_cache)
        try:
            rp = RobotFileParser()
            rp.set_url(BASE + "/robots.txt")
            rp.read()
            self._robots_allowed_cache = rp.can_fetch(self.user_agent, SEARCH_URL)
        except Exception:
            self._robots_allowed_cache = self.robots_fail_open
        return bool(self._robots_allowed_cache)

    @staticmethod
    def _published_at(text: str):
        t = (text or "").lower()
        now = datetime.now(timezone.utc)
        if "heute veröffentlicht" in t:
            return now
        if "gestern veröffentlicht" in t:
            return now - timedelta(days=1)
        m = re.search(r"vor\s+(\d+)\s+tagen?\s+veröffentlicht", t)
        if m:
            return now - timedelta(days=int(m.group(1)))
        if "vor 30+ tagen veröffentlicht" in t:
            return now - timedelta(days=31)
        return None


    @staticmethod
    def _clean_result_title(raw_title: str, company: str = "") -> str:
        """Remove BA result rank and duplicated trailing employer from the title."""
        title = re.sub(r"^\s*\d+\s*[:.]\s*", "", str(raw_title or ""), flags=re.I)
        title = re.sub(r"^\s*Ergebnis\s*:\s*", "", title, flags=re.I).strip()
        company = re.sub(r"\s+", " ", str(company or "")).strip()
        if company:
            # BA link labels often look like: `4: Mechanical Engineer ... bei Company GmbH`.
            # Employer is already a structured field, so keep it out of the canonical title.
            cpat = re.escape(company).replace(r"\ ", r"\s+")
            title = re.sub(rf"\s+bei\s+{cpat}\s*$", "", title, flags=re.I).strip()
        return re.sub(r"\s+", " ", title).strip()

    @staticmethod
    def _field(text: str, label: str, stop_labels: tuple[str, ...]) -> str:
        pattern = re.escape(label) + r"\s*:\s*(.+?)"
        if stop_labels:
            pattern += r"(?=(?:" + "|".join(re.escape(x) for x in stop_labels) + r")\s*:|$)"
        m = re.search(pattern, text, flags=re.I | re.S)
        return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""

    def _parse(self, html: str, limit: int) -> list[Job]:
        soup = BeautifulSoup(html, "html.parser")
        out: list[Job] = []
        seen: set[str] = set()
        for a in soup.find_all("a", href=True):
            href = str(a.get("href") or "")
            if "/jobsuche/jobdetail/" not in href:
                continue
            url = urljoin(BASE, href)
            if url in seen:
                continue
            seen.add(url)
            raw_title = a.get_text(" ", strip=True)
            # Find the smallest nearby container that contains employer/location metadata.
            node = a
            block_text = ""
            for _ in range(8):
                node = getattr(node, "parent", None)
                if node is None:
                    break
                text = re.sub(r"\s+", " ", node.get_text(" ", strip=True))
                if "Arbeitgeber:" in text and ("Arbeitsort:" in text or "Veröffentlichungsdatum:" in text):
                    block_text = text
                    break
            company = self._field(block_text, "Arbeitgeber", ("Arbeitsort", "Anstellungsart", "Befristung", "Veröffentlichungsdatum", "Änderungsdatum"))
            location = self._field(block_text, "Arbeitsort", ("Anstellungsart", "Befristung", "Veröffentlichungsdatum", "Änderungsdatum"))
            title = self._clean_result_title(raw_title, company)
            ref = url.rstrip("/").split("/")[-1]
            out.append(Job(
                source=self.name,
                source_id=ref or fingerprint(url),
                title=title,
                company=company,
                location=location,
                url=url,
                apply_url=url,
                description="",
                published_at=self._published_at(block_text),
                metadata={"reference": ref, "needs_enrichment": True, "discovery_provider": "Bundesagentur für Arbeit"},
            ))
            if len(out) >= limit:
                break
        return out

    def search(self, query: str, location: str, limit: int = 30) -> list[Job]:
        params = {
            "angebotsart": self._angebot_for(query),
            "was": query,
        }
        # BA accepts a free-text location. Germany-wide is the intended V1.7 default.
        if location:
            params["wo"] = "Deutschland" if location.lower() in {"germany", "deutschland"} else location
        url = SEARCH_URL + "?" + urlencode(params)
        if not self._robots_allowed():
            raise RuntimeError("robots.txt disallows automated Jobsuche search")
        self._wait()
        r = requests.get(url, timeout=self.timeout,
                         headers={"User-Agent": self.user_agent, "Accept": "text/html,application/xhtml+xml"})
        self._last_request = time.monotonic()
        r.raise_for_status()
        return self._parse(r.text, limit)
