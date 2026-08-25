
from __future__ import annotations
import hashlib, html, json, re
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
