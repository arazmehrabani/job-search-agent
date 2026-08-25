from __future__ import annotations
import re
from typing import Any
import requests

from .base import JobSource
from ..models import Job
from ..utils import parse_datetime, strip_html


class ArbeitnowSource(JobSource):
    """No-key Europe/DACH discovery source using Arbeitnow's public job-board API.

    The API is a catalogue feed rather than a query endpoint, so V1.7 downloads a
    small number of pages once per run and applies all selected search queries
    locally. This avoids one HTTP request per query.
    """

    name = "arbeitnow"
    category = "broad"

    def __init__(self, cfg: dict[str, Any] | None = None):
        self.cfg = cfg or {}
        self.pages = max(1, int(self.cfg.get("pages", 3) or 3))
        self.timeout = int(self.cfg.get("timeout_seconds", 25) or 25)
        self.country_terms = [
            str(x).lower() for x in (self.cfg.get("country_terms") or [
                "germany", "deutschland", "berlin", "hamburg", "munich", "münchen",
                "cologne", "köln", "frankfurt", "stuttgart", "bremen", "kiel",
                "dresden", "leipzig", "hannover", "nuremberg", "nürnberg",
                "düsseldorf", "dortmund", "essen", "karlsruhe", "augsburg",
                "rostock", "ulm", "erfurt", "wismar", "flensburg",
            ])
        ]

    def health(self) -> dict[str, Any]:
        return {"name": self.name, "category": self.category, "automatic": True,
                "configured": True, "operational": True,
                "reason": f"public API, no key; {self.pages} page(s) per run"}

    @staticmethod
    def _tokens(query: str) -> list[str]:
        return [x for x in re.findall(r"[a-zA-ZäöüÄÖÜß0-9+#.-]+", (query or "").lower()) if len(x) >= 3]

    def _in_germany(self, item: dict[str, Any]) -> bool:
        loc = str(item.get("location") or "").lower()
        if not loc:
            return False
        return any(term in loc for term in self.country_terms)

    def _matches_any_query(self, item: dict[str, Any], queries: list[str]) -> bool:
        hay = " ".join([
            str(item.get("title") or ""),
            strip_html(str(item.get("description") or "")),
            " ".join(str(x) for x in (item.get("tags") or [])),
            " ".join(str(x) for x in (item.get("job_types") or [])),
        ]).lower()
        title = str(item.get("title") or "").lower()
        generic = {
            "engineer", "engineering", "ingenieur", "ingenieurin", "working", "student",
            "werkstudent", "werkstudentin", "project", "development", "senior", "junior",
            "manager", "specialist", "intern", "internship", "praktikum",
        }
        for query in queries or [""]:
            q = (query or "").strip().lower()
            toks = self._tokens(query)
            if not toks:
                return True
            if q and q in title:
                return True
            specific = [t for t in toks if t not in generic]
            # V1.7 treated the word "engineer" as enough to match "mechanical engineer"
            # against every software/data engineer in the catalogue. V1.8 requires the
            # domain-bearing part of the query to match as well.
            if specific:
                title_hits = sum(1 for t in specific if t in title)
                hay_hits = sum(1 for t in specific if t in hay)
                if title_hits >= 1:
                    return True
                required = 1 if len(specific) == 1 else min(2, len(specific))
                if hay_hits >= required:
                    return True
            else:
                # A query made only of generic tokens is intentionally weak: require all
                # of them in the title rather than matching any one of them.
                if all(t in title for t in toks):
                    return True
        return False

    def _fetch_catalogue(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        url = "https://www.arbeitnow.com/api/job-board-api"
        for page in range(1, self.pages + 1):
            r = requests.get(url, params={"page": page}, timeout=self.timeout,
                             headers={"User-Agent": "JobSearchAgent/1.8"})
            r.raise_for_status()
            data = r.json()
            batch = data.get("data", []) if isinstance(data, dict) else []
            if not batch:
                break
            items.extend(x for x in batch if isinstance(x, dict))
            # Respect an API-provided final page when present.
            meta = data.get("meta") or {}
            last = meta.get("last_page")
            if last is not None:
                try:
                    if page >= int(last):
                        break
                except Exception:
                    pass
        return items

    def search(self, query: str, location: str, limit: int = 30) -> list[Job]:
        return self.search_many([query], [location], limit)

    def search_many(self, queries: list[str], locations: list[str], limit: int = 30) -> list[Job]:
        out: list[Job] = []
        for x in self._fetch_catalogue():
            if not self._in_germany(x):
                continue
            if not self._matches_any_query(x, queries):
                continue
            url = str(x.get("url") or "").strip()
            out.append(Job(
                source=self.name,
                source_id=str(x.get("slug") or url),
                title=str(x.get("title") or ""),
                company=str(x.get("company_name") or ""),
                location=str(x.get("location") or ""),
                url=url,
                apply_url=url,
                description=strip_html(str(x.get("description") or "")),
                published_at=parse_datetime(x.get("created_at")),
                metadata={
                    "remote": bool(x.get("remote", False)),
                    "tags": x.get("tags") or [],
                    "job_types": x.get("job_types") or [],
                    "discovery_provider": "Arbeitnow",
                },
            ))
            if len(out) >= max(limit, int(self.cfg.get("max_results_per_run", 120) or 120)):
                break
        return out
