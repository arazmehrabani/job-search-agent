
from __future__ import annotations
import requests
from .base import JobSource
from ..models import Job
from ..utils import parse_datetime, strip_html

class SmartRecruitersSource(JobSource):
    name = "smartrecruiters"
    def __init__(self, companies: list[dict]):
        self.companies = companies or []

    def search(self, query: str, location: str, limit: int = 30) -> list[Job]:
        out = []
        for cfg in self.companies:
            ident = cfg.get("identifier")
            if not ident:
                continue
            company_name = cfg.get("company", ident)
            url = f"https://api.smartrecruiters.com/v1/companies/{ident}/postings"
            params = {"q": query, "limit": min(limit,100), "destination":"PUBLIC"}
            r = requests.get(url, params=params, timeout=25)
            if r.status_code != 200:
                continue
            for x in r.json().get("content", []):
                pid = x.get("id") or x.get("uuid")
                detail_url = f"{url}/{pid}"
                dr = requests.get(detail_url, timeout=25)
                detail = dr.json() if dr.status_code == 200 else x
                loc = detail.get("location") or {}
                xloc = ", ".join(v for v in [loc.get("city"), loc.get("region"), loc.get("country")] if v)
                sections = detail.get("jobAd") or {}
                desc_parts = []
                if isinstance(sections, dict):
                    for v in sections.values():
                        if isinstance(v, dict):
                            desc_parts.extend(str(z) for z in v.values() if isinstance(z, str))
                        elif isinstance(v, str):
                            desc_parts.append(v)
                desc = strip_html(" ".join(desc_parts))
                apply_url = detail.get("applyUrl") or detail.get("ref") or ""
                out.append(Job(
                    source=self.name,
                    source_id=str(pid or ""),
                    title=detail.get("name") or x.get("name",""),
                    company=(detail.get("company") or {}).get("name") or company_name,
                    location=xloc,
                    url=apply_url,
                    apply_url=apply_url,
                    description=desc,
                    published_at=parse_datetime(detail.get("releasedDate") or x.get("releasedDate")),
                    metadata={"identifier": ident},
                ))
                if len(out) >= limit:
                    return out
        return out
