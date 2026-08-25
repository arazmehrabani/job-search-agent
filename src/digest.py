from __future__ import annotations
import html
import json
from pathlib import Path
from .db import Database


def build_digest(db: Database, output: str = "output/daily_digest.html", min_priority: int = 68) -> Path:
    rows = []
    for r in db.top_jobs(200):
        p = int(r["priority_score"] or 0)
        if p < min_priority or str(r["active_status"] or "") == "expired" or str(r["user_decision"] or "").upper() == "SKIP":
            continue
        try: m = json.loads(r["match_json"] or "{}")
        except Exception: m = {}
        rows.append((r, m))
    items = []
    for r, m in rows:
        items.append(
            f"<tr><td>{int(r['priority_score'] or 0)}</td><td>{int(r['match_score'] or 0)}</td>"
            f"<td><a href='{html.escape(r['url'] or '')}'>{html.escape(r['title'] or '')}</a></td>"
            f"<td>{html.escape(r['company'] or '')}</td><td>{html.escape(r['location'] or '')}</td>"
            f"<td>{html.escape(str(m.get('priority_label','')))}</td><td>{html.escape(str(r['user_decision'] or ''))}</td></tr>"
        )
    page = f"""<!doctype html><html><head><meta charset='utf-8'><title>Job Agent Review Digest</title>
<style>body{{font-family:Segoe UI,Arial;margin:28px;color:#20242a}}table{{border-collapse:collapse;width:100%;font-size:13px}}th,td{{padding:9px;border-bottom:1px solid #ddd;text-align:left}}a{{color:#1558b0;text-decoration:none}}h1{{margin-bottom:4px}}p{{color:#68707a}}</style></head><body>
<h1>Job Agent Review Digest</h1><p>{len(rows)} active job(s) with priority ≥ {min_priority}. High-priority packages may already have generated documents; review-priority roles are collected here without notification spam.</p>
<table><thead><tr><th>Priority</th><th>Fit</th><th>Role</th><th>Company</th><th>Location</th><th>Class</th><th>Your decision</th></tr></thead><tbody>{''.join(items)}</tbody></table></body></html>"""
    p=Path(output); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(page, encoding='utf-8'); return p
