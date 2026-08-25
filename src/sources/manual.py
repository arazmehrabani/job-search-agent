
from __future__ import annotations
from pathlib import Path
from .base import JobSource
from ..models import Job
from ..utils import fingerprint

class ManualLinksSource(JobSource):
    name = "manual"
    def __init__(self, file_path: str):
        self.file_path = Path(file_path)

    def search(self, query: str, location: str, limit: int = 30) -> list[Job]:
        if not self.file_path.exists():
            return []
        out=[]
        for line in self.file_path.read_text(encoding="utf-8").splitlines():
            u=line.strip()
            if not u or u.startswith("#"):
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
