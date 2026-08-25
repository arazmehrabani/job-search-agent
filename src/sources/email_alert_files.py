
from __future__ import annotations
from email import policy
from email.parser import BytesParser
from pathlib import Path
import re
from .base import JobSource
from ..models import Job
from ..utils import fingerprint

URL_RE = re.compile(r'https?://[^\s<>"\']+')

class EmailAlertFilesSource(JobSource):
    name = "email_alert"
    category = "inbox"
    def __init__(self, directory: str):
        self.directory=Path(directory)

    def health(self):
        count = len(list(self.directory.glob("*.eml"))) if self.directory.exists() else 0
        return {"name": self.name, "category": self.category, "automatic": True,
                "configured": self.directory.exists(), "operational": self.directory.exists(),
                "reason": f"{count} .eml alert file(s)" if self.directory.exists() else "alert directory missing"}

    def search(self, query: str, location: str, limit: int=30) -> list[Job]:
        if not self.directory.exists():
            return []
        out=[]
        for p in sorted(self.directory.glob("*.eml")):
            try:
                msg=BytesParser(policy=policy.default).parsebytes(p.read_bytes())
                subject=str(msg.get("subject",""))
                body=""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type()=="text/plain":
                            try: body += "\n"+part.get_content()
                            except Exception: pass
                else:
                    try: body=msg.get_content()
                    except Exception: body=""
                for u in URL_RE.findall(body):
                    if any(bad in u.lower() for bad in ("unsubscribe","privacy","tracking","preferences")):
                        continue
                    out.append(Job(
                        source=self.name,
                        source_id=fingerprint(str(p),u),
                        title=subject,
                        company="",
                        location="",
                        url=u.rstrip(".,)"),
                        apply_url=u.rstrip(".,)"),
                        metadata={"alert_file": str(p), "needs_enrichment": True}
                    ))
                    if len(out)>=limit:
                        return out
            except Exception:
                continue
        return out
