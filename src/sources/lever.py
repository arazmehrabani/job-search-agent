
from __future__ import annotations
import requests
from .base import JobSource
from ..models import Job
from ..utils import strip_html

class LeverSource(JobSource):
    name = "lever"
    category = "watchlist"
    def __init__(self, sites: list[dict]):
        self.sites = sites or []
        self._site_cache = {}

    def health(self):
        ok = bool(self.sites)
        return {"name": self.name, "category": self.category, "automatic": True,
                "configured": ok, "operational": ok,
                "reason": f"{len(self.sites)} site(s)" if ok else "enabled but no sites configured"}

    def search(self, query: str, location: str, limit: int = 30) -> list[Job]:
        out = []
        qwords = [w for w in (query or "").lower().split() if len(w)>2]
        for site_cfg in self.sites:
            site = site_cfg.get("site")
            if not site:
                continue
            company = site_cfg.get("company", site)
            region = site_cfg.get("region", "global")
            host = "api.eu.lever.co" if region == "eu" else "api.lever.co"
            url = f"https://{host}/v0/postings/{site}"
            cache_key = (region, site)
            if cache_key not in self._site_cache:
                r = requests.get(url, params={"mode":"json"}, timeout=25)
                self._site_cache[cache_key] = r.json() if r.status_code == 200 else []
            for x in self._site_cache.get(cache_key, []):
                desc = strip_html(" ".join([
                    x.get("descriptionPlain",""),
                    x.get("additionalPlain",""),
                    " ".join(s.get("content","") for s in x.get("lists",[]) if isinstance(s,dict)),
                ]))
                title = x.get("text","")
                hay = f"{title} {desc}".lower()
                if qwords and not any(w in hay for w in qwords):
                    continue
                categories = x.get("categories") or {}
                xloc = categories.get("location","")
                out.append(Job(
                    source=self.name,
                    source_id=str(x.get("id","")),
                    title=title,
                    company=company,
                    location=xloc,
                    url=x.get("hostedUrl",""),
                    apply_url=x.get("applyUrl",""),
                    description=desc,
                    published_at=None,
                    metadata={
                        "team": categories.get("team",""),
                        "commitment": categories.get("commitment",""),
                        "site": site,
                    }
                ))
                if len(out) >= limit:
                    return out
        return out
