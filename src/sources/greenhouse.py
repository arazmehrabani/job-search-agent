
from __future__ import annotations
import requests
from .base import JobSource
from ..models import Job
from ..utils import parse_datetime, strip_html

class GreenhouseSource(JobSource):
    name = "greenhouse"
    def __init__(self, boards: list[dict]):
        self.boards = boards or []

    def search(self, query: str, location: str, limit: int = 30) -> list[Job]:
        q = (query or "").lower()
        loc = (location or "").lower()
        out = []
        for board in self.boards:
            token = board.get("token")
            if not token:
                continue
            company = board.get("company", token)
            url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
            r = requests.get(url, params={"content": "true"}, timeout=25)
            if r.status_code != 200:
                continue
            for x in r.json().get("jobs", []):
                title = x.get("title","")
                xloc = (x.get("location") or {}).get("name","")
                desc = strip_html(x.get("content",""))
                hay = f"{title} {desc}".lower()
                if q and not all(term in hay for term in q.split()[:2]):
                    # loose filter: require first up to two words
                    continue
                if loc and location.lower() not in xloc.lower() and location.lower() != "germany":
                    pass
                out.append(Job(
                    source=self.name,
                    source_id=str(x.get("id","")),
                    title=title,
                    company=company,
                    location=xloc,
                    url=x.get("absolute_url",""),
                    apply_url=x.get("absolute_url",""),
                    description=desc,
                    published_at=parse_datetime(x.get("updated_at")),
                    metadata={"board_token": token},
                ))
                if len(out) >= limit:
                    return out
        return out
