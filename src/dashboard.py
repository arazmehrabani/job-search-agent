from __future__ import annotations
import html
import json
from pathlib import Path
from .db import Database


def _match_meta(raw: str | None) -> dict:
    try:
        return json.loads(raw or "{}")
    except Exception:
        return {}


def build_dashboard(db: Database, output="output/dashboard.html"):
    rows = db.top_jobs(300)
    stats = db.stats()
    trs = []
    for r in rows:
        url = html.escape(r["url"] or "")
        title = html.escape(r["title"] or "")
        company = html.escape(r["company"] or "")
        loc = html.escape(r["location"] or "")
        source = html.escape(r["source"] or "")
        active = html.escape(r["active_status"] or "")
        score = "" if r["match_score"] is None else str(r["match_score"])
        status = html.escape(r["status"] or "")
        date = html.escape((r["published_at"] or "")[:10])
        m = _match_meta(r["match_json"])
        lang = html.escape(str(m.get("job_language", ""))).upper()
        emp = html.escape(str(m.get("employment_type", "")))
        family = html.escape(str(m.get("career_family_label", "")))
        tier = html.escape(str(m.get("career_tier", "")))
        src_cv = html.escape(str(m.get("source_cv", "")))
        german_req = html.escape(str(m.get("german_requirement", "")))
        trs.append(
            f"<tr><td>{score}</td><td><a href='{url}'>{title}</a></td><td>{company}</td>"
            f"<td>{loc}</td><td>{lang}</td><td>{emp}</td><td>{german_req}</td><td>{family}</td><td>{tier}</td>"
            f"<td>{src_cv}</td><td>{date}</td><td>{source}</td><td>{active}</td><td>{status}</td></tr>"
        )
    page = f"""<!doctype html><html><head><meta charset="utf-8"><title>Job Agent Dashboard</title>
<style>
body{{font-family:Arial,sans-serif;margin:32px;max-width:1900px}}
.cards{{display:flex;gap:14px;margin-bottom:22px;flex-wrap:wrap}} .card{{border:1px solid #ddd;border-radius:10px;padding:14px;min-width:140px}}
table{{border-collapse:collapse;width:100%;font-size:13px}} th,td{{padding:8px;border-bottom:1px solid #ddd;text-align:left;vertical-align:top}}
th{{position:sticky;top:0;background:#fff}} a{{color:#0645ad;text-decoration:none}}
</style></head><body><h1>Job Search Agent V1.3</h1>
<div class="cards">
<div class="card"><b>Total</b><br>{stats.get('total',0)}</div>
<div class="card"><b>Active</b><br>{stats.get('active',0) or 0}</div>
<div class="card"><b>Score ≥78</b><br>{stats.get('strong',0) or 0}</div>
<div class="card"><b>Ready packages</b><br>{stats.get('packages',0) or 0}</div>
<div class="card"><b>Needs AI/review</b><br>{stats.get('needs_review',0) or 0}</div>
</div>
<table><thead><tr><th>Score</th><th>Role</th><th>Company</th><th>Location</th><th>Lang</th><th>Type</th><th>German req.</th><th>Career family</th><th>Tier</th><th>Source CV</th><th>Date</th><th>Source</th><th>Live</th><th>Status</th></tr></thead>
<tbody>{''.join(trs)}</tbody></table></body></html>"""
    p = Path(output)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(page, encoding="utf-8")
    return p
