
from __future__ import annotations
from pathlib import Path
from .base import JobSource
from ..models import Job
from ..utils import fingerprint, is_safe_http_url

class ManualLinksSource(JobSource):
    name = "manual"
    category = "manual"
    automatic = False
    def __init__(self, file_path: str):
        self.file_path = Path(file_path)

    def health(self):
        count = 0
        if self.file_path.exists():
            count = sum(1 for x in self.file_path.read_text(encoding="utf-8").splitlines() if x.strip() and not x.strip().startswith("#"))
        return {"name": self.name, "category": self.category, "automatic": False,
                "configured": self.file_path.exists(), "operational": self.file_path.exists(),
                "reason": f"{count} manual URL(s)" if self.file_path.exists() else "manual URL file missing"}

    def search(self, query: str, location: str, limit: int = 30) -> list[Job]:
        if not self.file_path.exists():
            return []
        out=[]
        for line in self.file_path.read_text(encoding="utf-8").splitlines():
            u=line.strip()
            if not u or u.startswith("#"):
                continue
            if not is_safe_http_url(u):
                continue
            out.append(Job(
                source=self.name,
                source_id=fingerprint(u),
                title="",
                company="",
                location="",
                url=u,
                apply_url=u,
                metadata={"needs_enrichment": True}
            ))
            if len(out)>=limit:
                break
        return out
