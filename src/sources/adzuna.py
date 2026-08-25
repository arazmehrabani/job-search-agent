
from __future__ import annotations
import os, requests
from .base import JobSource
from ..models import Job
from ..utils import parse_datetime, strip_html

class AdzunaSource(JobSource):
    name = "adzuna"
    category = "broad"
    def __init__(self, country="de"):
        self.country = country
        self.app_id = os.getenv("ADZUNA_APP_ID", "")
        self.app_key = os.getenv("ADZUNA_APP_KEY", "")

    def available(self):
        return bool(self.app_id and self.app_key)

    def health(self):
        ok = self.available()
        return {"name": self.name, "category": self.category, "automatic": True,
                "configured": ok, "operational": ok,
                "reason": "ready" if ok else "ADZUNA_APP_ID / ADZUNA_APP_KEY missing"}

    def search(self, query: str, location: str, limit: int = 30) -> list[Job]:
        if not self.available():
            return []
        url = f"https://api.adzuna.com/v1/api/jobs/{self.country}/search/1"
        params = {
            "app_id": self.app_id,
            "app_key": self.app_key,
            "results_per_page": min(limit, 50),
            "what": query,
            "where": location,
            "sort_by": "date",
            "content-type": "application/json",
        }
        r = requests.get(url, params=params, timeout=25)
        r.raise_for_status()
        out = []
        for x in r.json().get("results", []):
            out.append(Job(
                source=self.name,
                source_id=str(x.get("id","")),
                title=x.get("title",""),
                company=(x.get("company") or {}).get("display_name",""),
                location=(x.get("location") or {}).get("display_name",""),
                url=x.get("redirect_url",""),
                apply_url=x.get("redirect_url",""),
                description=strip_html(x.get("description","")),
                published_at=parse_datetime(x.get("created")),
                salary_min=x.get("salary_min"),
                salary_max=x.get("salary_max"),
                metadata={"category": (x.get("category") or {}).get("label","")},
            ))
        return out
