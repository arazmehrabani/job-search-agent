
from __future__ import annotations
import hashlib, html, json, re
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from datetime import datetime, timezone
from pathlib import Path
from bs4 import BeautifulSoup

def strip_html(value: str) -> str:
    if not value:
        return ""
    soup = BeautifulSoup(value, "html.parser")
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()

def normalize_text(value: str) -> str:
    value = (value or "").lower()
    value = re.sub(r"[^a-z0-9äöüß+#. ]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()

def safe_slug(value: str, max_len: int = 70) -> str:
    value = normalize_text(value).replace(" ", "_")
    value = re.sub(r"[^a-z0-9äöüß_+-]", "", value)
    return (value[:max_len] or "unknown").strip("_")

def fingerprint(*parts: str) -> str:
    raw = "||".join(normalize_text(x) for x in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

def parse_datetime(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    s = str(value).strip()
    # normalize common trailing Z
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        pass
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s[:10], fmt).replace(tzinfo=timezone.utc)
        except Exception:
            continue
    return None

def extract_json(text: str) -> dict:
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except Exception:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start:end+1])
        raise

def latex_escape(text: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
        "_": r"\_", "{": r"\{", "}": r"\}",
        "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(ch, ch) for ch in (text or ""))

def env_expand(value: str) -> str:
    import os
    if not isinstance(value, str):
        return value
    pattern = re.compile(r"\$\{([A-Z0-9_]+)(?::-([^}]*))?\}")
    def repl(m):
        return os.getenv(m.group(1), m.group(2) or "")
    return pattern.sub(repl, value)


TRACKING_QUERY_KEYS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "src", "source", "ref", "referrer", "trackingid", "tracking_id", "gh_src",
    "lever-source", "fbclid", "gclid", "msclkid",
}

def canonical_url(url: str) -> str:
    """Return a stable vacancy URL without fragments and common tracking parameters."""
    if not url:
        return ""
    try:
        parts = urlsplit(url.strip())
        query = []
        for k, v in parse_qsl(parts.query, keep_blank_values=True):
            if k.lower() not in TRACKING_QUERY_KEYS:
                query.append((k, v))
        path = re.sub(r"/{2,}", "/", parts.path or "/")
        # Ashby /application and overview routes identify the same vacancy.
        if parts.netloc.lower().endswith("ashbyhq.com"):
            path = re.sub(r"/application/?$", "", path)
        return urlunsplit((parts.scheme.lower() or "https", parts.netloc.lower(), path.rstrip("/") or "/", urlencode(query), ""))
    except Exception:
        return (url or "").split("#", 1)[0].split("?", 1)[0].rstrip("/")

def source_identity(job) -> str:
    """Use semantic identity when parsed fields are trustworthy; otherwise URL/ID."""
    company = normalize_text(str(getattr(job, "company", "") or ""))
    title = normalize_text(str(getattr(job, "title", "") or ""))
    location = normalize_text(str(getattr(job, "location", "") or ""))
    generic_titles = {"", "job", "unknown job", "job title not parsed"}
    generic_companies = {"", "unknown company", "company not parsed", "jobs", "careers"}
    if title not in generic_titles and company not in generic_companies:
        return f"semantic:{company}|{title}|{location}"

    source_id = str(getattr(job, "source_id", "") or "").strip()
    url = canonical_url(str(getattr(job, "url", "") or ""))
    if source_id and str(getattr(job, "source", "")) not in {"manual", "email_alert"}:
        return f"source:{normalize_text(str(getattr(job, 'source', '')))}:{normalize_text(source_id)}"
    if url:
        return f"url:{url}"
    return f"fallback:{company}|{title}|{location}"

def job_fingerprint(job) -> str:
    return hashlib.sha256(source_identity(job).encode("utf-8")).hexdigest()[:24]
