
from __future__ import annotations
import os, requests
from .base import JobSource
from ..models import Job
from ..utils import parse_datetime, strip_html

class JoobleSource(JobSource):
    name = "jooble"
    def __init__(self):
        self.api_key = os.getenv("JOOBLE_API_KEY", "")

    def available(self):
        return bool(self.api_key)

    def search(self, query: str, location: str, limit: int = 30) -> list[Job]:
        if not self.available():
            return []
        url = f"https://jooble.org/api/{self.api_key}"
        payload = {
            "keywords": query,
            "location": location,
            "page": 1,
            "ResultOnPage": min(limit, 50)
        }
        r = requests.post(url, json=payload, timeout=25)
        r.raise_for_status()
        out = []
        for x in r.json().get("jobs", []):
            out.append(Job(
                source=self.name,
                source_id=str(x.get("id") or x.get("link","")),
                title=x.get("title",""),
                company=x.get("company",""),
                location=x.get("location",""),
                url=x.get("link",""),
                apply_url=x.get("link",""),
                description=strip_html(x.get("snippet","")),
                published_at=parse_datetime(x.get("updated")),
                metadata={"type": x.get("type",""), "source_name": x.get("source","")},
            ))
        return out
